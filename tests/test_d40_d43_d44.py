"""R2 第二批：D40（同版本号判绿）/ D43（🟡 二分与计数）/ D44（分隔线宽度自洽）。"""
from __future__ import annotations

import io

from modcheck.cli.render import render_report, table_width, ROW_PREFIX_WIDTH
from modcheck.console import Console, display_width
from modcheck.core.checker import classify
from modcheck.core.models import (FileInfo, Loader, MatchStatus, ModEntry, ReasonCode, Status,
                                  VersionInfo)
from modcheck.core.report import (Report, ReportItem, actionable_degraded, advice_text,
                                  build_action_hints, needs_action)


def V(number: str, mc: tuple[str, ...]) -> VersionInfo:
    """构造版本对象。"""
    return VersionInfo(version_id="V" + number, version_number=number, name=number,
                       project_id="P", date_published="2026-09-18T00:00:00Z",
                       version_type="release", game_versions=mc, loaders=("fabric",),
                       files=(FileInfo("f.jar", "u", True, 1, {}),))


def item(current: str | None, reason: ReasonCode, status: Status, **kw: object) -> ReportItem:
    """构造报告条目。"""
    entry = ModEntry(key="k", display_name="K", mod_id="k", current_version=current)
    return ReportItem(mod=entry, status=status, reason=reason,
                      reason_key="reason.old_version_only", hint_key="advice.old_version_only",
                      current_version=current, **kw)  # type: ignore[arg-type]


# ---------------------------------------------------------------- D40
def test_same_version_number_is_ready() -> None:
    """D40：最新版与兼容版版本号相同时判 🟢 OK_SAME_VERSION_NUMBER。

    实测样例：entityculling 目标 26.1，最新版 1.11.2（支持 26.3），兼容版 1.11.2（支持 26.1）。
    """
    newest = V("1.11.2", ("26.3",))
    compat = V("1.11.2", ("26.1",))
    result = classify(loader=Loader.FABRIC, mc_version="26.1",
                      releases_for_loader=[newest], compat_releases=[compat])
    assert result.status is Status.READY
    assert result.reason is ReasonCode.OK_SAME_VERSION_NUMBER


def test_different_version_number_still_degraded() -> None:
    """版本号不同仍然是 🟡（不能顺手把真降级也判绿）。"""
    newest = V("31.8.0.49", ("26.3",))
    compat = V("29.34.0.90", ("26.1",))
    result = classify(loader=Loader.FABRIC, mc_version="26.1",
                      releases_for_loader=[newest], compat_releases=[compat])
    assert result.status is Status.DEGRADED
    assert result.reason is ReasonCode.OLD_VERSION_ONLY


# ---------------------------------------------------------------- D43
def test_needs_action_split() -> None:
    """本地就是可用最新版 -> 无需处理；落后 -> 需要替换。"""
    same = item("26.1", ReasonCode.OLD_VERSION_ONLY, Status.DEGRADED,
                latest_compat=V("26.1", ("26.1",)), latest_for_loader=V("26.3", ("26.3",)))
    older = item("26.0", ReasonCode.OLD_VERSION_ONLY, Status.DEGRADED,
                 latest_compat=V("26.1", ("26.1",)), latest_for_loader=V("26.3", ("26.3",)))
    assert needs_action(same) is False
    assert needs_action(older) is True


def test_advice_text_wording() -> None:
    """建议行：无需处理 vs 将 X 替换为 Y。"""
    report = Report(mc_version="26.1", loader=Loader.FABRIC, profile_name="p", generated_at="t")
    same = item("26.1", ReasonCode.OLD_VERSION_ONLY, Status.DEGRADED,
                latest_compat=V("26.1", ("26.1",)), latest_for_loader=V("26.3", ("26.3",)))
    older = item("26.0", ReasonCode.OLD_VERSION_ONLY, Status.DEGRADED,
                 latest_compat=V("26.1", ("26.1",)), latest_for_loader=V("26.3", ("26.3",)))
    assert advice_text(same, report).startswith("无需处理")
    assert advice_text(older, report) == "将 26.0 替换为 26.1"


def test_next_step_counts_only_actionable() -> None:
    """D43：「下一步」的 🟡 计数只统计需要动作的。"""
    report = Report(mc_version="26.1", loader=Loader.FABRIC, profile_name="p", generated_at="t")
    report.add(item("26.1", ReasonCode.OLD_VERSION_ONLY, Status.DEGRADED,
                    latest_compat=V("26.1", ("26.1",)), latest_for_loader=V("26.3", ("26.3",))))
    report.add(item("26.1", ReasonCode.OLD_VERSION_ONLY, Status.DEGRADED,
                    latest_compat=V("26.1", ("26.1",)), latest_for_loader=V("26.3", ("26.3",))))
    report.add(item("26.0", ReasonCode.OLD_VERSION_ONLY, Status.DEGRADED,
                    latest_compat=V("26.1", ("26.1",)), latest_for_loader=V("26.3", ("26.3",))))
    assert actionable_degraded(report) == 1
    hints = build_action_hints(report)
    step2 = [line for line in hints if "再确认" in line]
    assert step2 and "的 1 个" in step2[0]


# ---------------------------------------------------------------- D44
def _render(report: Report) -> str:
    stream = io.StringIO()
    console = Console(stream=stream, color="never", width=200)
    console.is_tty = False
    console.width = 200
    render_report(report, console)
    return stream.getvalue()


def test_separator_width_matches_content() -> None:
    """D44：所有分隔线的显示宽度 == 表格实际宽度（不再出现 200 vs 116 的脱节）。"""
    report = Report(mc_version="26.3", loader=Loader.FABRIC, profile_name="p", generated_at="t")
    report.add(item("26.1", ReasonCode.OLD_VERSION_ONLY, Status.DEGRADED,
                    latest_compat=V("26.1", ("26.1",)), latest_for_loader=V("26.3", ("26.3",))))
    text = _render(report)
    rules = {display_width(line) for line in text.splitlines()
             if line and set(line) == {"═"}}
    body = [line for line in text.splitlines()
            if line.startswith("  ") and ("→" in line or "（已是最新" in line)]
    assert rules, "没有找到分隔线"
    assert len(rules) == 1, rules
    width = rules.pop()
    assert width < 200, "分隔线不该再用那个与内容无关的 200"
    if body:
        widest = max(display_width(line) for line in body)
        assert width >= widest, (width, widest)
        assert width - widest <= 12, "线与内容脱节"


def test_table_width_helper() -> None:
    """表格宽度 = 行首 + 三列 + 列间距（+ 日期列）。"""
    assert table_width((10, 5, 8), False) == ROW_PREFIX_WIDTH + 10 + 2 + 5 + 2 + 8
    assert table_width((10, 5, 8), True) == ROW_PREFIX_WIDTH + 10 + 2 + 5 + 2 + 8 + 2 + 10
