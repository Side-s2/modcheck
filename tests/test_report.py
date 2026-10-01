"""T-10 报告数据结构测试：8 种结论 + 汇总双恒等式 + 逐字文案。"""
from __future__ import annotations

from modcheck.core.checker import Classification, for_reason
from modcheck.core.models import Loader, ModEntry, ReasonCode, SourceKind, Status
from modcheck.core.report import (GROUP_ORDER, Report, ReportItem, build_action_hints,
                                  origin_line, reason_text, summary_line, verdict_line)
from modcheck.i18n import t


def item(key: str, status: Status, reason: ReasonCode, **kw: object) -> ReportItem:
    """构造一条报告条目。"""
    entry = ModEntry(key=key, display_name=key, mod_id=key)
    base = Classification(status=status, reason=reason,
                          reason_key="reason." + reason.value.lower(),
                          hint_key="advice." + reason.value.lower())
    return ReportItem(mod=entry, status=status, reason=reason,
                      reason_key=str(kw.pop("reason_key", base.reason_key)),
                      hint_key=str(kw.pop("hint_key", base.hint_key)), **kw)  # type: ignore[arg-type]


def make_report(*items: ReportItem, **kw: object) -> Report:
    """构造一份报告。"""
    report = Report(mc_version=str(kw.pop("mc_version", "26.3")), loader=Loader.FABRIC,
                    profile_name=str(kw.pop("profile_name", "服务器A")),
                    generated_at="2026-10-01 21:03:12", **kw)  # type: ignore[arg-type]
    for entry in items:
        report.add(entry)
    return report


def test_group_order() -> None:
    """分组顺序：阻塞 -> 仅存测试版 -> 需注意 -> 未判定 -> 就绪 -> 已忽略。"""
    assert GROUP_ORDER == (Status.BLOCKED, Status.PRERELEASE, Status.DEGRADED, Status.UNKNOWN,
                           Status.READY, Status.IGNORED)


def test_summary_identities() -> None:
    """两条汇总恒等式必须成立（主 Agent 裁决）。"""
    report = make_report(
        item("a", Status.READY, ReasonCode.OK),
        item("b", Status.READY, ReasonCode.OK),
        item("c", Status.DEGRADED, ReasonCode.OLD_VERSION_ONLY),
        item("d", Status.BLOCKED, ReasonCode.NO_LOADER),
        item("e", Status.UNKNOWN, ReasonCode.ERROR),
        item("f", Status.IGNORED, ReasonCode.IGNORED),
    )
    data = report.summary
    assert data["total_all"] == 6
    assert data["total_checked"] == 5
    assert (data["ready"] + data["degraded"] + data["prerelease"] + data["blocked"]
            + data["unknown"] == data["total_checked"])
    assert data["total_checked"] + data["ignored"] == data["total_all"]
    assert report.verify_identities() is True
    assert data["ignored"] == 1


def test_summary_excludes_ignored_from_total_checked() -> None:
    """已忽略不进"本次检查"的统计。"""
    report = make_report(item("a", Status.IGNORED, ReasonCode.IGNORED),
                         item("b", Status.IGNORED, ReasonCode.IGNORED))
    assert report.summary["total_checked"] == 0
    assert report.summary["total_all"] == 2
    assert report.verify_identities() is True


def test_verdict_all_ready() -> None:
    """全部就绪。"""
    report = make_report(item("a", Status.READY, ReasonCode.OK))
    assert report.verdict().value == "all_ready"


def test_verdict_ready_with_degraded() -> None:
    """有需降级、无阻塞无未判定。"""
    report = make_report(item("a", Status.READY, ReasonCode.OK),
                         item("b", Status.DEGRADED, ReasonCode.OLD_VERSION_ONLY))
    assert report.verdict().value == "ready_with_degraded"


def test_verdict_blocked_and_all_blocked() -> None:
    """有阻塞；全部阻塞是独立结论。"""
    report = make_report(item("a", Status.BLOCKED, ReasonCode.NO_LOADER),
                         item("b", Status.READY, ReasonCode.OK))
    assert report.verdict().value == "blocked"
    all_blocked = make_report(item("a", Status.BLOCKED, ReasonCode.NO_LOADER),
                              item("b", Status.BLOCKED, ReasonCode.NO_MC_VERSION))
    assert all_blocked.verdict().value == "all_blocked"


def test_verdict_incomplete_and_all_unknown() -> None:
    """有未判定（无阻塞）；全部未判定是独立结论。"""
    report = make_report(item("a", Status.READY, ReasonCode.OK),
                         item("b", Status.UNKNOWN, ReasonCode.ERROR))
    assert report.verdict().value == "incomplete"
    all_unknown = make_report(item("a", Status.UNKNOWN, ReasonCode.ERROR),
                              item("b", Status.UNKNOWN, ReasonCode.UNMATCHED))
    assert all_unknown.verdict().value == "all_unknown"


def test_verdict_empty() -> None:
    """空清单。"""
    assert make_report().verdict().value == "empty"


def test_verdict_interrupted_wins() -> None:
    """被中断时无论其它分组如何，结论都是"不完整"。"""
    report = make_report(item("a", Status.BLOCKED, ReasonCode.NO_LOADER),
                         interrupted=True, completed=3, total=10)
    assert report.verdict().value == "interrupted"


def test_iter_items_follows_group_order() -> None:
    """遍历顺序 = 分组顺序，组内保持清单原始顺序。"""
    report = make_report(
        item("ready1", Status.READY, ReasonCode.OK),
        item("blocked1", Status.BLOCKED, ReasonCode.NO_LOADER),
        item("blocked2", Status.BLOCKED, ReasonCode.NO_MC_VERSION),
        item("unknown1", Status.UNKNOWN, ReasonCode.ERROR),
    )
    assert [entry.mod.key for entry in report.iter_items()] == [
        "blocked1", "blocked2", "unknown1", "ready1"]


def test_to_dict_shape() -> None:
    """导出的 JSON 结构：schema_version + 每条 item 的 status/reason。"""
    report = make_report(item("a", Status.BLOCKED, ReasonCode.NO_LOADER),
                         item("b", Status.READY, ReasonCode.OK))
    report.source_stats = {SourceKind.HASH: 3, SourceKind.FILENAME: 1}
    data = report.to_dict()
    assert data["schema_version"] == 1
    assert data["loader"] == "fabric"
    assert data["verdict"] == "blocked"
    assert data["summary"]["blocked"] == 1  # type: ignore[index]
    assert data["source_stats"] == {"hash": 3, "filename": 1}  # type: ignore[index]
    groups = data["groups"]  # type: ignore[assignment]
    assert list(groups) == [s.value for s in GROUP_ORDER]  # type: ignore[arg-type]
    first = groups["blocked"][0]  # type: ignore[index]
    assert first["reason"] == "NO_LOADER"
    assert first["status"] == "blocked"


def test_verdict_lines_wording() -> None:
    """结论行逐字（PRD §5.4）。"""
    ready = make_report(item("a", Status.READY, ReasonCode.OK))
    assert verdict_line(ready) == "结论：✅ 可以升级到 Minecraft 26.3（Fabric）—— 1 个模组全部就绪"
    blocked = make_report(item("a", Status.BLOCKED, ReasonCode.NO_LOADER),
                          item("b", Status.UNKNOWN, ReasonCode.ERROR))
    assert verdict_line(blocked) == "结论：❌ 现在还不能升级到 Minecraft 26.3 —— 2 个模组中有 1 个阻塞、1 个未判定"
    empty = make_report()
    assert verdict_line(empty) == "结论：⚠️ 这次没有检查任何模组 —— 清单「服务器A」里没有任何模组。"


def test_summary_line_has_two_totals() -> None:
    """汇总行同时给出"共多少个"和"本次检查多少个"。"""
    report = make_report(item("a", Status.READY, ReasonCode.OK),
                         item("b", Status.IGNORED, ReasonCode.IGNORED))
    line = summary_line(report)
    assert "共 2 个模组" in line
    assert "本次检查 1 个" in line
    assert "⚫ 已忽略 1" in line


def test_origin_line_counts() -> None:
    """识别来源行四个计数。"""
    report = make_report(item("a", Status.READY, ReasonCode.OK))
    report.source_stats = {SourceKind.HASH: 9, SourceKind.JAR_META: 3, SourceKind.FILENAME: 1}
    line = origin_line(report)
    assert "Modrinth 文件指纹 9" in line
    assert "jar 内信息 3" in line
    assert "名称搜索 0" in line
    assert "文件名猜测 1" in line


def test_action_hints_dynamic() -> None:
    """下一步按实际存在的组动态生成；没有问题项时整段替换。"""
    clean = make_report(item("a", Status.READY, ReasonCode.OK))
    assert build_action_hints(clean) == [t("report.next.none")]
    dirty = make_report(item("a", Status.BLOCKED, ReasonCode.NO_LOADER),
                        item("b", Status.DEGRADED, ReasonCode.OLD_VERSION_ONLY),
                        item("c", Status.UNKNOWN, ReasonCode.ERROR))
    hints = build_action_hints(dirty)
    assert hints[0] == "下一步："
    assert len(hints) == 5
    assert "modcheck check --profile 服务器A --mc 26.3 --loader fabric --refresh" in hints[-1]


def test_reason_text_no_loader_lists_loaders() -> None:
    """NO_LOADER 的原因里要写明它实际发布了哪些加载器（E26）。"""
    report = make_report()
    entry = item("create", Status.BLOCKED, ReasonCode.NO_LOADER,
                 reason_key="reason.no_loader", hint_key="advice.no_loader",
                 available_loaders=("forge", "neoforge"))
    text = reason_text(entry, report)
    assert text == "该模组没有 Fabric 版本（它只发布了 Forge、NeoForge 版本）"


def test_reason_text_no_mc_version_uses_max() -> None:
    """NO_MC_VERSION 要附"最高只支持到"某版本。"""
    report = make_report()
    entry = item("cf", Status.BLOCKED, ReasonCode.NO_MC_VERSION,
                 reason_key="reason.no_mc_version", hint_key="advice.no_mc_version",
                 max_supported_mc="1.20.1")
    assert reason_text(entry, report) == "最高只支持 MC 1.20.1，没有任何支持 26.3 的版本"


def test_for_reason_status_mapping() -> None:
    """for_reason 的状态映射：404 -> 阻塞，网络错误 -> 未判定。"""
    assert for_reason(ReasonCode.NOT_FOUND).status is Status.BLOCKED
    assert for_reason(ReasonCode.ERROR).status is Status.UNKNOWN
    assert for_reason(ReasonCode.IGNORED).status is Status.IGNORED
