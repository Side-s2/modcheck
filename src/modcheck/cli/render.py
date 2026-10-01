"""报告渲染（**排版合同**，PRD §5.3/§5.4）。

硬性规则：
  * 分隔线：顶部/结论后用 ═，组内用 ─，长度 = 终端显示宽度；
  * 行首：2 空格 + 1 状态符号 + 1 空格 + 3 列右对齐序号 + 1 空格；
  * 列宽全报告统一：名称 <= 26、modid <= 20、版本 <= 34、日期 10，列间 2 空格；
  * 表格内**禁止 emoji**，只用单宽符号 ✓ ! ✗ ? ·（emoji 宽度算法不一致会错位）；
  * 空组不打印标题；
  * 全部按显示宽度（CJK 算 2 列）对齐。
"""
from __future__ import annotations

from typing import Sequence

from modcheck.console import (SYMBOL_BLOCKED, SYMBOL_DEGRADED, SYMBOL_IGNORED, SYMBOL_READY,
                              SYMBOL_UNKNOWN, Console, pad, truncate)
from modcheck.core.filename import parse_jar_filename
from modcheck.core.models import ReasonCode, SourceKind, Status
from modcheck.core.report import (GROUP_ORDER, Report, ReportItem, advice_text,
                                  build_action_hints, origin_line, reason_text, summary_line,
                                  verdict_line)
from modcheck.i18n import t

#: 各列宽上限
NAME_WIDTH = 26
MODID_WIDTH = 20
VERSION_WIDTH = 34
DATE_WIDTH = 10
#: 详情行缩进
DETAIL_INDENT = " " * 10
#: 组标题
GROUP_TITLE_KEYS = {
    Status.BLOCKED: "group.blocked.title",
    Status.DEGRADED: "group.degraded.title",
    Status.UNKNOWN: "group.unknown.title",
    Status.READY: "group.ready.title",
    Status.IGNORED: "group.ignored.title",
}
GROUP_SYMBOLS = {
    Status.BLOCKED: SYMBOL_BLOCKED,
    Status.DEGRADED: SYMBOL_DEGRADED,
    Status.UNKNOWN: SYMBOL_UNKNOWN,
    Status.READY: SYMBOL_READY,
    Status.IGNORED: SYMBOL_IGNORED,
}


def short_date(value: str) -> str:
    """ISO 时间戳 -> YYYY-MM-DD；拿不到就返回占位符。"""
    text = (value or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return t("report.item.empty_cell")


def version_label(item: ReportItem) -> str:
    """版本列里的"最新版"文字：version_number（必要时附主文件名里的模组版本）。"""
    version = item.latest_for_loader
    if version is None:
        return t("report.item.empty_cell")
    label = version.version_number or version.name or t("report.item.empty_cell")
    file_info = version.primary_file
    if file_info is not None:
        parsed = parse_jar_filename(file_info.filename)
        mod_version = parsed.mod_version
        # 文件名里 + 与 - 常被作者当同一种分隔符用（实测 sodium 就是），
        # 判断"是否已包含"前先归一化，避免显示成 0.9.3-alpha.1 (0.9.3+alpha.1)
        contained = bool(mod_version) and (mod_version in label
                                           or mod_version.replace("+", "-") in label
                                           or mod_version.replace("-", "+") in label)
        if mod_version and not contained:
            candidate = label + " (" + mod_version + ")"
            if len(candidate) <= VERSION_WIDTH:
                return candidate
    return label


def render_version_cell(item: ReportItem) -> str:
    """版本列：{你当前} → {加载器最新}（PRD §5.3.1）。

    特殊情况（主 Agent 裁决）：🟡 且"你当前"恰好就是最新兼容版时，
    **不显示那个看起来像降级的箭头**，只显示当前版本。
    """
    current = item.current_version or t("report.item.empty_cell")
    if item.reason is ReasonCode.OLD_VERSION_ONLY and item.latest_compat is not None \
            and item.current_version and item.current_version == item.latest_compat.version_number:
        return current
    latest = version_label(item)
    if item.reason is ReasonCode.IGNORED:
        return current
    # 两侧相同时箭头没有信息量（0.7.0 → 0.7.0）；
    # 🟡 组里更别扭：看起来像自相矛盾的降级，其实原因是"只有测试版支持"。
    if item.current_version and item.current_version == latest:
        if item.status is Status.DEGRADED:
            return t("report.item.same_version_release", version=current)
        return t("report.item.same_version", version=current)
    return current + " → " + latest


def column_widths(items: Sequence[ReportItem]) -> tuple[int, int, int]:
    """全报告统一的列宽（取实际最大值，但不超过上限）。"""
    from modcheck.console import display_width

    name = modid = version = 0
    for item in items:
        name = max(name, display_width(name_cell(item)))
        modid = max(modid, display_width(modid_cell(item)))
        version = max(version, display_width(render_version_cell(item)))
    return (min(name, NAME_WIDTH), min(modid, MODID_WIDTH), min(version, VERSION_WIDTH))


def name_cell(item: ReportItem) -> str:
    """名称列：有中文名 -> [中文名] 英文名。"""
    entry = item.mod
    if entry.cn_name:
        base = "[" + entry.cn_name + "] " + (entry.display_name or entry.mod_id or entry.key)
    else:
        base = entry.display_name or entry.mod_id or entry.key or t("report.item.empty_cell")
    return truncate(base, NAME_WIDTH)


def modid_cell(item: ReportItem) -> str:
    """modid 列：猜测来源前缀 ~（PRD §5.3）。"""
    from modcheck.core.models import SourceKind as _SK

    entry = item.mod
    raw = entry.mod_id or entry.key or t("report.item.empty_cell")
    if entry.source_kind is _SK.FILENAME or entry.match_status.value == "guess":
        raw = "~" + raw
    return truncate(raw, MODID_WIDTH)


def _row(item: ReportItem, index: int, widths: tuple[int, int, int]) -> str:
    """拼一条主体行。"""
    symbol = GROUP_SYMBOLS.get(item.status, SYMBOL_UNKNOWN)
    return ("  " + symbol + " " + f"{index:>3}" + " "
            + pad(name_cell(item), widths[0]) + "  "
            + pad(modid_cell(item), widths[1]) + "  "
            + pad(render_version_cell(item), widths[2]) + "  "
            + short_date(item.latest_for_loader.date_published if item.latest_for_loader else ""))


def render_report(report: Report, console: Console, *, quiet: bool = False) -> None:
    """渲染整份报告（PRD §5.3 的排版合同）。"""
    console.clear_progress()
    header = t("report.header.title")
    console.line("═" * console.width)
    console.line(header)
    if report.profile_saved:
        console.line(t("report.header.profile", name=report.profile_name,
                       count=report.summary["total_all"]))
    else:
        console.line(t("report.header.profile_temp", name=report.profile_name,
                       count=report.summary["total_all"]))
    console.line(t("report.header.target", mc=report.mc_version,
                   loader=report.loader.display_name))
    console.line(t("report.header.sources", modrinth=report.source_status[0],
                   curseforge=report.source_status[1]))
    console.line(origin_line(report))
    console.line(t("report.header.time", time=report.generated_at,
                   elapsed=f"{report.elapsed:.0f}", requests=report.requests_made,
                   cache_hits=report.cache_hits))
    console.line("═" * console.width)
    console.line(verdict_line(report))
    if report.verdict().value == "all_blocked":
        console.line(t("verdict.all_blocked.hint"))
    console.line()

    items = list(report.iter_items())
    widths = column_widths(items)
    for status in GROUP_ORDER:
        group = report.groups.get(status, [])
        if not group:
            continue  # 空组不打印标题
        console.line(_group_title(status, group, report))
        console.rule("─")
        if status is Status.READY and quiet:
            console.line(t("group.ready.quiet", count=len(group)))
            console.line()
            continue
        for index, item in enumerate(group, start=1):
            console.line(_row(item, index, widths))
            _render_details(item, report, console)
        console.line()

    if any(entry.source_kind is SourceKind.FILENAME for entry in
           (item.mod for item in report.iter_items())):
        console.line(t("report.origin.guess_note"))
        console.line()
    console.line(summary_line(report))
    console.line("═" * console.width)
    console.line()
    render_next_steps(report, console)


def _group_title(status: Status, group: Sequence[ReportItem], report: Report) -> str:
    """组标题（逐字 + 数量）。"""
    return t(GROUP_TITLE_KEYS[status], count=len(group), mc=report.mc_version,
             loader=report.loader.display_name)


def _render_details(item: ReportItem, report: Report, console: Console) -> None:
    """按组渲染详情行（🔴 3 行 / 🟡 4 行 / ⚪ 3 行 / 🟢 1 行 / ⚫ 1 行）。"""
    if item.status is Status.READY:
        if item.provider_message:
            console.line(t("report.item.reason", text=item.provider_message))
        return
    if item.status is Status.IGNORED:
        console.line(DETAIL_INDENT + advice_text(item, report))
        return
    console.line(t("report.item.reason", text=reason_text(item, report)))
    if item.status is Status.DEGRADED:
        _render_available(item, report, console)
    console.line(t("report.item.advice", text=advice_text(item, report)))


def _render_available(item: ReportItem, report: Report, console: Console) -> None:
    """🟡 的「可用：」行。"""
    if item.reason is ReasonCode.OLD_VERSION_ONLY and item.latest_compat is not None:
        version = item.latest_compat
        if item.current_version and item.current_version == version.version_number:
            console.line(t("report.item.already_latest"))
            return
        console.line(t("report.item.available", version=version.version_number,
                       date=short_date(version.date_published)))
        return
    if item.latest_any is not None:
        console.line(t("report.item.available_channel",
                       version=item.latest_any.version_number,
                       channel=item.latest_any.version_type))


def render_summary(report: Report, console: Console) -> None:
    """只渲染汇总行。"""
    console.line(summary_line(report))


def render_next_steps(report: Report, console: Console) -> None:
    """渲染「下一步」（没有问题项时整段替换）。"""
    summary = report.summary
    if summary["total_checked"] == 0:
        console.line(t("verdict.empty", name=report.profile_name))
        console.line()
        console.line(t("report.next.title"))
        console.line(t("report.empty.next1"))
        console.line(t("report.empty.command", dir="<mods 文件夹>", profile=report.profile_name))
        console.line(t("report.empty.next2"))
        return
    for line in build_action_hints(report):
        console.line(line)


__all__ = ["render_report", "render_summary", "render_next_steps", "render_version_cell",
           "column_widths", "version_label", "short_date", "name_cell", "modid_cell"]
