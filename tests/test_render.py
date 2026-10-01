"""T-18 渲染测试：排版合同（列宽、符号、空组、quiet、版本列规则）。"""
from __future__ import annotations

import io

from modcheck.cli.render import (column_widths, modid_cell, name_cell, render_report,
                                 render_version_cell, short_date, version_label)
from modcheck.console import Console, display_width
from modcheck.core.models import FileInfo, MatchStatus, ModEntry, ReasonCode, SourceKind, Status, VersionInfo
from modcheck.core.report import Report, ReportItem


def V(number: str, *, mc: tuple[str, ...] = ("26.3",), vtype: str = "release",
      date: str = "2026-09-18T10:00:00Z", filename: str = "") -> VersionInfo:
    """构造版本对象。"""
    files = (FileInfo(filename=filename, url="u", primary=True, size=1, hashes={}),) if filename else ()
    return VersionInfo(version_id="V_" + number, version_number=number, name=number,
                       project_id="P", date_published=date, version_type=vtype,
                       game_versions=mc, loaders=("fabric",), files=files)


def item(key: str, status: Status, reason: ReasonCode, **kw: object) -> ReportItem:
    """构造报告条目。"""
    current = kw.pop("current", None)
    entry = ModEntry(key=key, display_name=str(kw.pop("display", key)),
                     cn_name=kw.pop("cn_name", None), mod_id=key,  # type: ignore[arg-type]
                     source_kind=kw.pop("source_kind", None),  # type: ignore[arg-type]
                     match_status=kw.pop("match_status", MatchStatus.EXACT),  # type: ignore[arg-type]
                     current_version=current)  # type: ignore[arg-type]
    return ReportItem(mod=entry, status=status, reason=reason,
                      reason_key="reason." + reason.value.lower(),
                      hint_key="advice." + reason.value.lower(),
                      current_version=current, **kw)  # type: ignore[arg-type]


def make_console() -> tuple[Console, io.StringIO]:
    """内存控制台。"""
    stream = io.StringIO()
    return Console(stream=stream, color="never", width=100), stream


def test_short_date() -> None:
    """日期列只取 YYYY-MM-DD。"""
    assert short_date("2026-09-18T10:00:00.000Z") == "2026-09-18"
    assert short_date("") == "—"


def test_version_label_appends_mod_version() -> None:
    """version_number 里没有主文件名的模组版本时追加显示（PRD §5.3.1）。"""
    assert version_label(item("a", Status.READY, ReasonCode.OK,
                              latest_for_loader=V("26.3", filename="fabric-carpet-26.3+v260915.jar"))) \
        == "26.3 (v260915)"
    assert version_label(item("b", Status.READY, ReasonCode.OK,
                              latest_for_loader=V("0.9.3-alpha.1",
                                                  filename="sodium-neoforge-0.9.3-alpha.1+mc26.3.jar"))) \
        == "0.9.3-alpha.1"


def test_version_cell_arrow_and_placeholder() -> None:
    """版本列：{你当前} → {最新}；缺失侧显示破折号。"""
    ready = item("a", Status.READY, ReasonCode.OK, current="26.1",
                 latest_for_loader=V("26.3"))
    assert render_version_cell(ready) == "26.1 → 26.3"
    missing = item("b", Status.BLOCKED, ReasonCode.NO_MC_VERSION, current=None,
                   latest_for_loader=V("6.0.8"))
    assert render_version_cell(missing) == "— → 6.0.8"


def test_version_cell_hides_downgrade_arrow_when_already_latest_compat() -> None:
    """决策：当前版本 == 最新兼容版时，不显示那个看起来像降级的箭头。"""
    entry = item("jei", Status.DEGRADED, ReasonCode.OLD_VERSION_ONLY, current="29.34.0.90",
                 latest_for_loader=V("19.51.0.418"), latest_compat=V("29.34.0.90"))
    assert render_version_cell(entry) == "29.34.0.90"


def test_same_version_shows_no_arrow() -> None:
    """两侧版本相同时不画箭头（0.7.0 → 0.7.0 是噪音）。"""
    ready = item("fa", Status.READY, ReasonCode.OK, current="0.7.0",
                 latest_for_loader=V("0.7.0"))
    assert render_version_cell(ready) == "0.7.0（已是最新）"
    degraded = item("gca", Status.PRERELEASE, ReasonCode.PRERELEASE_ONLY,
                    current="v2.12.1+build.83", latest_for_loader=V("v2.12.1+build.83"))
    assert render_version_cell(degraded) == "v2.12.1+build.83（已是最新正式版）"


def test_name_and_modid_cells() -> None:
    """名称列带中文名；猜测来源的 modid 前缀 ~。"""
    with_cn = item("carpet", Status.READY, ReasonCode.OK, display="Carpet", cn_name="地毯")
    assert name_cell(with_cn) == "[地毯] Carpet"
    guessed = item("thermal", Status.BLOCKED, ReasonCode.NOT_FOUND,
                   source_kind=SourceKind.FILENAME, match_status=MatchStatus.GUESS)
    assert modid_cell(guessed).startswith("~")


def test_column_widths_are_capped() -> None:
    """列宽按显示宽度算且不超过上限。"""
    items = [item("a", Status.READY, ReasonCode.OK, display="X" * 60, cn_name="中" * 30,
                  current="1" * 50, latest_for_loader=V("2" * 50))]
    name, modid, version = column_widths(items)
    assert name <= 26
    assert modid <= 20
    assert version <= 34


def test_render_report_layout_rules() -> None:
    """排版硬性规则：顶部/底部 ═、组内 ─、空组不打印、表格内无 emoji。"""
    console, stream = make_console()
    report = Report(mc_version="26.3", loader=__import__("modcheck.core.models", fromlist=["Loader"]).Loader.FABRIC,
                    profile_name="demo", generated_at="2026-10-01 21:03:12")
    report.add(item("carpet", Status.READY, ReasonCode.OK, display="Carpet", cn_name="地毯",
                    current="26.1", latest_for_loader=V("26.3")))
    report.add(item("create", Status.BLOCKED, ReasonCode.NO_LOADER, display="Create",
                    available_loaders=("forge", "neoforge")))
    render_report(report, console)
    text = stream.getvalue()
    # D44：分隔线宽度 = 表格实际宽度（不再是与内容无关的终端宽度）
    rules = {display_width(line) for line in text.splitlines() if line and set(line) == {"═"}}
    assert rules and len(rules) == 1, rules
    group_rules = {display_width(line) for line in text.splitlines()
                   if line and set(line) == {"─"}}
    assert group_rules == rules
    assert "🔴 阻塞（1 个）" in text
    assert "🟢 就绪（1 个）" in text
    assert "🟡 需注意（" not in text        # 空组不打印（汇总行里的计数不算）
    assert "🟠 仅存测试版（" not in text
    body = [line for line in text.splitlines() if line.startswith("  ✓") or line.startswith("  ✗")]
    assert body, "没有渲染出条目行"
    for line in body:
        assert "🔴" not in line and "🟢" not in line   # 表格内禁止 emoji
    assert "✗   1" in text                   # 3 列右对齐序号
    assert "          原因：" in text         # 详情行缩进 10


def test_render_quiet_hides_ready_details() -> None:
    """--quiet：就绪组只显示数量，🔴/🟡 仍逐条列出。"""
    console, stream = make_console()
    report = Report(mc_version="26.3", loader=__import__("modcheck.core.models", fromlist=["Loader"]).Loader.FABRIC,
                    profile_name="demo", generated_at="t")
    report.add(item("carpet", Status.READY, ReasonCode.OK, display="Carpet"))
    report.add(item("create", Status.BLOCKED, ReasonCode.NO_LOADER, display="Create"))
    render_report(report, console, quiet=True)
    text = stream.getvalue()
    assert "（1 个，已省略明细）" in text
    assert "✗   1" in text


def test_render_summary_has_both_totals() -> None:
    """汇总行同时给出总数与本次检查数。"""
    console, stream = make_console()
    report = Report(mc_version="26.3", loader=__import__("modcheck.core.models", fromlist=["Loader"]).Loader.FABRIC,
                    profile_name="demo", generated_at="t")
    report.add(item("a", Status.READY, ReasonCode.OK))
    render_report(report, console)
    assert "共 1 个模组，本次检查 1 个" in stream.getvalue()
