"""check 子命令：功能①的主检查（PRD §4.2 / §5.3）。"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Sequence
from modcheck.cli.commands.export import (default_filename, export_csv, export_json,
                                          export_markdown)
from modcheck.cli.context import AppContext, loader_from_args
from modcheck.cli.render import render_report
from modcheck.core.checker_run import check_all
from modcheck.core.matching import candidate_names, format_downloads, rank_candidates
from modcheck.core.mcversion import validate_target_version
from modcheck.core.models import MatchStatus, ModEntry, ProjectHit
from modcheck.core.report import Report, ReportItem, Verdict
from modcheck.errors import ConfigError, ModcheckError, ProviderError, UserCancelled
from modcheck.i18n import t
from modcheck.providers.mojang import MojangVersions
from modcheck.storage.profiles import (list_profiles, load_profile, profile_path,
                                       save_profile)

#: 退出码映射（PRD §10.4）
VERDICT_EXIT = {
    Verdict.BLOCKED: 1,
    Verdict.ALL_BLOCKED: 1,
    Verdict.INCOMPLETE: 2,
    Verdict.ALL_UNKNOWN: 2,
    Verdict.INTERRUPTED: 130,
}


def _load_profile_entries(args: argparse.Namespace, ctx: AppContext
                          ) -> tuple[list[ModEntry], str, bool, str, Path | None]:
    """决定这次检查用哪份模组清单。

    返回：
        (条目列表, 清单名, 是否已保存, 目录来源或空串, 清单文件路径或 None)
    """
    profile_name = getattr(args, "profile", None)
    file_arg = getattr(args, "file", None)
    mods_dir = getattr(args, "mods_dir", None)
    if profile_name and mods_dir:
        raise ConfigError(t("err.profile.mutex"))
    if mods_dir:
        directory = Path(mods_dir)
        if not directory.is_dir():
            raise ConfigError(t("err.dir.not_found", path=directory))
        from modcheck.cli.commands.scan import scan_dirs

        report = scan_dirs([directory], ctx)
        return report.entries, directory.name, False, str(directory), None
    path = Path(file_arg) if file_arg else None
    if path is None:
        if not profile_name:
            raise ConfigError(t("err.no_profile_selected"))
        path = profile_path(ctx.profiles_dir, profile_name)
        if not path.exists():
            available = "、".join(p.name for p in list_profiles(ctx.profiles_dir))
            raise ConfigError(t("err.profile.not_found", name=profile_name,
                                available=available or t("err.profile.none_available")))
    profile = load_profile(path)
    return profile.mods, profile.name or path.stem, True, "", path


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
    entries, profile_name, saved, _source, profile_file = _load_profile_entries(args, ctx)
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

    report = Report(mc_version=str(mc_version), loader=loader, profile_name=profile_name,
                    generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                    source_status=ctx.registry.status_line(), profile_saved=saved,
                    total=len(entries))
    start = time.monotonic()
    blocked_seen = 0

    step = max(1, len(entries) // 5)

    def on_done(done: int, total: int, entry: ModEntry, item: ReportItem) -> None:
        nonlocal blocked_seen
        if item.status.value == "blocked":
            blocked_seen += 1
        if quiet:
            return
        if console.is_tty:
            console.progress(_progress_line(done, total, entry.best_name, blocked_seen,
                                            time.monotonic() - start, console.width))
        elif done % step == 0 or done == total:
            # 重定向/管道：每 20% 打一行，绝不写回车
            console.line(t("progress.percent", done=done, total=total))

    if len(entries) < 3 and not quiet:
        console.progress(t("progress.simple"))

    # 交互模式才允许弹窗（PRD §5.7）；非交互模式绝不问、也绝不猜
    changed: dict[str, bool] = {"flag": False}
    matcher = None
    if ctx.interactive and ctx.prompter is not None:
        matcher = make_interactive_matcher(ctx, changed, profile_name)

    try:
        items = check_all(entries, provider, loader=loader, mc_version=str(mc_version),
                          window=window, prerelease=prerelease, jobs=jobs,
                          resolve=bool(getattr(args, "resolve", False)), on_done=on_done,
                          interactive_match=matcher)
    except UserCancelled:
        console.clear_progress()
        report.interrupted = True
        console.line(t("progress.interrupted", done=report.completed, total=len(entries)))
        report.elapsed = time.monotonic() - start
        _save_if_changed(changed, entries, profile_file, saved, ctx)
        render_report(report, console, quiet=quiet)
        return 130
    except KeyboardInterrupt:
        # S12：中断后 1 秒内给结论，绝不打印 traceback
        console.clear_progress()
        report.interrupted = True
        console.line(t("progress.interrupted", done=report.completed, total=len(entries)))
        report.elapsed = time.monotonic() - start
        _save_if_changed(changed, entries, profile_file, saved, ctx)
        render_report(report, console, quiet=quiet)
        return 130

    console.clear_progress()
    for item in items:
        report.add(item)
    report.completed = len(items)
    report.elapsed = time.monotonic() - start
    report.requests_made, report.cache_hits = ctx.client.stats
    for item in items:
        kind = item.mod.source_kind
        if kind is not None:
            report.source_stats[kind] = report.source_stats.get(kind, 0) + 1

    _save_if_changed(changed, entries, profile_file, saved, ctx)
    render_report(report, console, quiet=quiet)
    _export(report, args, ctx)
    if report.interrupted:
        return 130
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


__all__ = ["run_check", "VERDICT_EXIT"]
