"""check 子命令：解析参数 -> 调 flows.check_flow -> 渲染报告（PRD §4.2 / §5.3）。

流程（选清单、跑 check_all、统计、判数据源可用性）全在 flows/check_flow.py；
这里只剩：参数与交互的装配、把 console 包成进度回调、把 Report 渲染出来、映射退出码。
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Sequence

from modcheck.cli.commands.export import (default_filename, export_csv, export_json,
                                          export_markdown)
from modcheck.cli.commands.scan import scan_progress_callback
from modcheck.cli.context import AppContext, loader_from_args, provider_or_none
from modcheck.cli.render import render_report
from modcheck.core.matching import candidate_names, format_downloads, rank_candidates
from modcheck.core.mcversion import validate_target_version
from modcheck.core.models import MatchStatus, ModEntry, ProjectHit
from modcheck.core.report import Report, Verdict
from modcheck.errors import (EXIT_NO_SOURCE, ConfigError, ModcheckError, ProviderError,
                             UserCancelled)
from modcheck.flows.check_flow import (load_profile_entries, run_check_flow,
                                       source_unavailable)
from modcheck.i18n import t
from modcheck.providers.mojang import MojangVersions
from modcheck.storage.profiles import load_profile, save_profile

#: 退出码映射（PRD §10.4）
VERDICT_EXIT = {
    Verdict.BLOCKED: 1,
    Verdict.ALL_BLOCKED: 1,
    Verdict.INCOMPLETE: 2,
    Verdict.ALL_UNKNOWN: 2,
    Verdict.INTERRUPTED: 130,
}


def _progress_line(done: int, total: int, name: str, blocked: int, elapsed: float,
                   console_width: int) -> str:
    """按终端宽度分级拼装进度行（PRD §5.5）。"""
    if console_width < 80:
        return t("progress.line.tiny", done=done, total=total)
    filled = int(done / total * 20) if total else 0
    bar = "#" * filled + "-" * (20 - filled)
    if console_width >= 110:
        return t("progress.line.full", total=total, bar=bar, done=done, name=name,
                 elapsed=int(elapsed), blocked=blocked, eta=max(1, int(elapsed / max(done, 1) * (total - done))))
    if console_width >= 100:
        return t("progress.line.mid", total=total, bar=bar, done=done, name=name,
                 elapsed=int(elapsed))
    return t("progress.line.short", total=total, bar=bar, done=done, elapsed=int(elapsed))


def _slug_from_input(raw: str) -> str | None:
    """从用户输入里取 slug：支持裸 slug 与 modrinth.com 链接。"""
    text = (raw or "").strip().rstrip("/")
    if not text:
        return None
    if "modrinth.com" in text:
        parts = [part for part in text.split("/") if part]
        for marker in ("mod", "project"):
            if marker in parts:
                index = parts.index(marker)
                if index + 1 < len(parts):
                    return parts[index + 1]
        return parts[-1] if parts else None
    return text


def make_interactive_matcher(ctx: AppContext, changed: dict[str, bool],
                             profile_name: str):
    """构造 PRD §5.7 的匹配交互回调（1-5 / m / s / i / q）。

    仅在交互模式下会被调用；非交互模式绝不会问用户，也绝不猜。
    """
    console = ctx.console
    prompter = ctx.prompter

    def matcher(entry: ModEntry, hits: Sequence[ProjectHit]) -> str | None:
        console.clear_progress()
        console.line(t("match.warn.title", name=entry.best_name))
        console.line()
        ranked = list(rank_candidates(hits, candidate_names(entry)))[:5]
        if ranked:
            console.line(t("match.candidates.header"))
            for index, hit in enumerate(ranked, start=1):
                console.line(t("match.candidate.item", index=index, title=hit.title,
                               slug=hit.slug, downloads=format_downloads(hit.downloads)))
                console.line(t("match.candidate.desc", description=hit.description[:60]))
            console.line()
        console.line(t("match.option.select"))
        console.line(t("match.option.manual"))
        console.line(t("match.option.skip"))
        console.line(t("match.option.ignore"))
        console.line(t("match.option.quit"))
        while True:
            raw = prompter.ask(t("match.prompt")).lower()
            if raw.isdigit() and ranked and 1 <= int(raw) <= len(ranked):
                hit = ranked[int(raw) - 1]
                entry.sources["modrinth"] = hit.slug
                entry.match_status = MatchStatus.MANUAL
                changed["flag"] = True
                console.line(t("match.recorded", name=entry.best_name, title=hit.title,
                               slug=hit.slug))
                console.line(t("match.recorded.hint", profile=profile_name))
                return hit.slug
            if raw == "m":
                slug = _slug_from_input(prompter.ask(t("match.manual.prompt")))
                if slug:
                    entry.sources["modrinth"] = slug
                    entry.match_status = MatchStatus.MANUAL
                    changed["flag"] = True
                    console.line(t("match.recorded", name=entry.best_name, title=slug, slug=slug))
                    console.line(t("match.recorded.hint", profile=profile_name))
                    return slug
            elif raw == "s":
                console.line(t("match.skipped", name=entry.best_name))
                return None
            elif raw == "i":
                entry.match_status = MatchStatus.IGNORED
                changed["flag"] = True
                console.line(t("match.ignored", name=entry.best_name))
                console.line(t("match.ignored.hint", profile=profile_name))
                return None
            elif raw == "q":
                raise UserCancelled(t("menu.bye"))
            console.line(t("menu.invalid_choice"))

    return matcher


def run_check(args: argparse.Namespace, ctx: AppContext) -> int:
    """执行一次兼容性检查；返回退出码。"""
    console = ctx.console
    source = load_profile_entries(
        profiles_dir=ctx.profiles_dir,
        profile=getattr(args, "profile", None),
        file=getattr(args, "file", None),
        mods_dir=getattr(args, "mods_dir", None),
        # --mods-dir 那条路径要现场扫一遍文件夹：进度画法与 scan 子命令完全一致
        provider=provider_or_none(ctx),
        on_progress=scan_progress_callback(console))
    console.clear_progress()
    entries = source.entries
    loader = loader_from_args(args, ctx)

    mc_version = getattr(args, "mc", None) or ctx.settings.default_mc_version
    if not mc_version:
        raise ConfigError(t("err.mc.invalid", value=""))
    # 先校验格式（不联网、立即失败），再取官方清单做存在性校验 —— 参数写错不该先等一次网络
    validate_target_version(str(mc_version), None)
    known: set[str] | None = None
    try:
        known = MojangVersions(ctx.client).known_versions()
    except ProviderError:
        console.line(t("warn.mojang_unavailable"))
    validate_target_version(str(mc_version), known)

    provider = ctx.registry.primary()  # 无可用数据源 -> 退出码 4
    window = int(getattr(args, "window", None) or 25)
    if window < 5 and ctx.debug:
        console.line(t("err.debug.window_small", window=window))
    prerelease = bool(getattr(args, "pre", False))
    jobs = int(ctx.settings.concurrency)
    quiet = bool(getattr(args, "quiet", False))

    # 交互模式才允许弹窗（PRD §5.7）；非交互模式绝不问、也绝不猜
    changed: dict[str, bool] = {"flag": False}
    matcher = None
    if ctx.interactive and ctx.prompter is not None:
        matcher = make_interactive_matcher(ctx, changed, source.name)

    if len(entries) < 3 and not quiet:
        console.progress(t("progress.simple"))

    start = time.monotonic()
    blocked_seen = 0
    step = max(1, len(entries) // 5)

    def on_progress(done: int, total: int, name: str) -> None:
        """通用进度：非 TTY 下每 20% 打一行（回车会污染管道输出）。"""
        if quiet or console.is_tty:
            return
        if done % step == 0 or done == total:
            console.line(t("progress.percent", done=done, total=total))

    def on_item(done: int, total: int, entry: ModEntry, item) -> None:
        """逐条进度：TTY 下的进度行要知道"已发现几个阻塞"。"""
        nonlocal blocked_seen
        if item.status.value == "blocked":
            blocked_seen += 1
        if quiet or not console.is_tty:
            return
        console.progress(_progress_line(done, total, entry.best_name, blocked_seen,
                                        time.monotonic() - start, console.width))

    outcome = run_check_flow(
        entries, provider=provider, loader=loader, mc_version=str(mc_version), window=window,
        prerelease=prerelease, jobs=jobs, resolve=bool(getattr(args, "resolve", False)),
        on_progress=on_progress, on_item=on_item, interactive_match=matcher,
        stats_source=ctx.client, profile_name=source.name, profile_saved=source.saved,
        source_status=ctx.registry.status_line())
    report = outcome.report

    console.clear_progress()
    if report.interrupted:
        # S12：中断后 1 秒内给结论，绝不打印 traceback（报告由 flow 标成 interrupted）
        console.line(t("progress.interrupted", done=report.completed, total=len(entries)))
        _save_if_changed(changed, entries, source.path, source.saved, ctx)
        render_report(report, console, quiet=quiet)
        return 130

    _save_if_changed(changed, entries, source.path, source.saved, ctx)
    render_report(report, console, quiet=quiet)
    _export(report, args, ctx)
    if source_unavailable(outcome):
        # E01：一个可用数据源都没有 —— 这比"有几个模组没查到"严重得多，
        # 脚本里必须能靠退出码区分「网络/代理坏了」与「部分未判定」。
        console.line()
        for line in t("err.net.offline").splitlines():
            console.line(line)
        return EXIT_NO_SOURCE
    return VERDICT_EXIT.get(report.verdict(), 0)


def _save_if_changed(changed: dict[str, bool], entries: list[ModEntry],
                     profile_file: Path | None, saved: bool, ctx: AppContext) -> None:
    """交互里选定的匹配写回清单（仅当清单本来就在磁盘上）。

    决策：临时清单（--mods-dir）不写盘；用户没确认过的条目也不会被静默改写。
    """
    if not changed.get("flag") or not saved or profile_file is None:
        return
    try:
        profile = load_profile(profile_file)
        profile.mods = entries
        save_profile(profile, profile_file)
        ctx.console.line(t("profile.updated", name=profile.name))
    except ModcheckError as exc:
        ctx.console.line(exc.message)


def _export(report: Report, args: argparse.Namespace, ctx: AppContext) -> None:
    """按 --json/--md/--csv 导出（导出内容不受 --quiet 影响）。"""
    for attr, exporter, ext in (("json_out", export_json, "json"),
                                ("md_out", export_markdown, "md"),
                                ("csv_out", export_csv, "csv")):
        raw = getattr(args, attr, None)
        if not raw:
            continue
        target = Path(raw)
        if target.is_dir():
            target = target / default_filename(report.profile_name, report.mc_version,
                                               report.loader, ext)
        exporter(report, target)
        ctx.console.line(str(target))


__all__ = ["make_interactive_matcher", "run_check", "VERDICT_EXIT"]
