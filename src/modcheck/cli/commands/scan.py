"""scan 子命令：解析参数 -> 调 flows.scan_flow -> 渲染终端输出。

流水线本身（列目录、读 jar、指纹反查、同名搜索、合并去重）全在 flows/scan_flow.py，
这里只剩三件事：
    ① 把命令行参数与数据源交给流程；
    ② 把 console 包成进度回调（TTY 画进度行，非 TTY 每 20% 打一行）；
    ③ 渲染统计、与已有清单合并后原子写盘。
"""
from __future__ import annotations

import argparse
from pathlib import Path

from modcheck.cli.context import AppContext, provider_or_none
from modcheck.core.filename import parse_jar_filename
from modcheck.core.models import ModEntry
from modcheck.errors import ConfigError, EXIT_INTERRUPTED
from modcheck.flows.scan_flow import (DEFAULT_PROFILE, ScanReport, scan_dirs, scan_from_list)
from modcheck.i18n import t
from modcheck.storage.profiles import (MergeStats, load_profile, merge_entries, new_profile,
                                       profile_path, save_profile)


def scan_progress_callback(console):
    """把终端包成扫描进度回调（flows 只报数字，怎么画由这里决定）。

    TTY：原地刷进度行；非 TTY：每 20% 打一行（回车会污染管道/重定向输出）。
    """
    def on_progress(done: int, total: int, name: str) -> None:
        filled = int(done / total * 20) if total else 20
        console.progress(t("scan.progress.reading", bar="█" * filled + "░" * (20 - filled),
                           done=done, total=total, name=name))
        step = max(1, total // 5)
        if not console.is_tty and (done % step == 0 or done == total):
            console.line(t("scan.progress.plain", done=done, total=total))

    return on_progress


# ---------------------------------------------------------------- 命令入口
def run_scan(args: argparse.Namespace, ctx: AppContext) -> int:
    """scan 子命令入口；返回退出码。"""
    console = ctx.console
    profile_name = getattr(args, "profile", None) or DEFAULT_PROFILE
    from_list = getattr(args, "from_list", None)
    # 数据源不可用不阻断扫描：只用 jar 内信息也能建清单（flows 会记一条提示）
    provider = provider_or_none(ctx)

    if from_list:
        source = Path(from_list)
        console.line(t("scan.from_list.header", path=source, lines=_count_lines(source)))
        console.line(t("scan.from_list.warn"))
        report = scan_from_list(source, provider=provider)
        console.clear_progress()
        candidates_total = sum(len(parse_jar_filename(entry.file_name or "").name_candidates)
                               for entry in report.entries)
        named = sum(1 for entry in report.entries
                    if parse_jar_filename(entry.file_name or "").name_candidates)
        console.line(t("scan.from_list.parsed", total=len(report.entries),
                       candidates=candidates_total, named=named))
        _print_from_list_stats(report, console)
    else:
        paths = [Path(p) for p in (getattr(args, "paths", None) or [])]
        if not paths:
            raise ConfigError(t("err.scan.no_dir"))
        for directory in paths:
            console.line(t("scan.header", dir=directory))
        report = scan_dirs(paths, provider=provider,
                           on_progress=scan_progress_callback(console))
        console.clear_progress()
        _print_dir_stats(report, console)

    if report.cancelled:
        # 只有传了 should_stop 的调用方才会走到这里（CLI 今天不传）：
        # 半份扫描结果**绝不能**落盘，否则用户的清单会被悄悄改窄。
        console.line(t("scan.cancelled"))
        return EXIT_INTERRUPTED

    if not report.entries and not report.skipped:
        console.line(t("err.dir.no_jar", path=paths[0] if not from_list else from_list))
        return 0

    profile_file = profile_path(ctx.profiles_dir, profile_name)
    existing_entries: list[ModEntry] = []
    if not getattr(args, "new", False) and profile_file.exists():
        existing_entries = load_profile(profile_file).mods
    else:
        if not profile_file.exists():
            console.line(t("scan.profile_not_exist", name=profile_name))

    merged, stats = merge_entries(existing_entries, report.entries)
    profile = new_profile(profile_name)
    if profile_file.exists() and not getattr(args, "new", False):
        profile = load_profile(profile_file)
    profile.mods = merged
    save_profile(profile, profile_file)

    _print_dupe_block(stats, console)
    console.line(t("scan.summary", profile=profile_name, added=stats.added,
                   merged=stats.merged, skipped=len(report.skipped), total=len(merged)))
    console.line(t("scan.profile_file", path=profile_file))
    return 0


def _count_lines(path: Path) -> int:
    """数一下文件行数（读不到就返回 0）。"""
    try:
        return len(path.read_text(encoding="utf-8-sig").splitlines())
    except OSError:
        return 0


def _print_dir_stats(report: ScanReport, console) -> None:
    """打印目录模式的统计（PRD §5.8）。"""
    console.line(t("scan.read", count=report.files_seen - len(report.skipped)))
    if report.skipped:
        console.line(t("scan.skipped.header", count=len(report.skipped)))
        for item in report.skipped:
            console.line(t("scan.skipped.item", name=item.name, reason=item.reason))
    if report.subdirs:
        console.line(t("scan.subdir", count=len(report.subdirs), names="、".join(report.subdirs)))
    console.line(t("scan.identify.header"))
    console.line(t("scan.identify.hash", count=report.by_hash))
    console.line(t("scan.identify.meta", count=report.by_meta))
    console.line(t("scan.identify.search", count=report.by_search))
    if report.unidentified:
        console.line(t("scan.identify.unidentified", count=len(report.unidentified)))
        for name in report.unidentified:
            console.line(t("scan.unidentified.item", name=name))
    if report.guessed:
        console.line(t("scan.noninteractive_unmatched", count=report.guessed))
    for warning in report.warnings:
        console.line(warning)


def _print_from_list_stats(report: ScanReport, console) -> None:
    """打印仅文件名模式的统计。"""
    matched = sum(1 for entry in report.entries if entry.sources.get("modrinth"))
    console.line(t("scan.from_list.identify_header"))
    console.line(t("scan.from_list.matched", count=matched))
    console.line(t("scan.from_list.unmatched", count=len(report.entries) - matched))
    unnamed = sum(1 for entry in report.entries if not entry.display_name)
    if unnamed:
        console.line(t("scan.from_list.unnamed", count=unnamed))
    console.line(t("scan.from_list.hint"))
    for warning in report.warnings:
        console.line(warning)


def _print_dupe_block(stats: MergeStats, console) -> None:
    """同一 modid 多文件时必须显式告警（会让服务器启动失败的真实事故）。"""
    for warning in stats.warnings:
        console.line(warning)


__all__ = ["DEFAULT_PROFILE", "run_scan", "scan_progress_callback"]
