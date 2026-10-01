"""检查报告数据结构（纯数据 + 结论），供 CLI 与未来 GUI 消费。

分组顺序固定为 🔴 阻塞 -> 🟠 仅存测试版 -> 🟡 需注意 -> ⚪ 未判定 -> 🟢 就绪 -> ⚫ 已忽略。
（🟠 排在 🟡 前面：只有测试版可用比"退一个稳定版"风险更高。）
汇总行同时给出"共多少个"与"本次检查多少个"，并有两条恒等式（主 Agent 裁决）：
    ① ready + degraded + prerelease + blocked + unknown == total_checked
    ② total_checked + ignored == total_all
summary 是按分组长度算出来的，所以两条恒等式**构造上必然成立**；
verify_identities() 供测试与导出前自检使用。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator, Sequence

from modcheck.core.models import (Loader, ModEntry, ReasonCode, SourceKind, Status,
                                  VersionInfo)
from modcheck.i18n import t

#: 报告分组顺序（问题优先，就绪最后，已忽略永远最后）
GROUP_ORDER: tuple[Status, ...] = (
    Status.BLOCKED, Status.PRERELEASE, Status.DEGRADED,
    Status.UNKNOWN, Status.READY, Status.IGNORED)

#: 参与"本次检查"统计的五组（不含已忽略）
CHECKED_STATUSES: tuple[Status, ...] = (
    Status.BLOCKED, Status.PRERELEASE, Status.DEGRADED, Status.UNKNOWN, Status.READY)

#: 需要用户留意的两组：🟠 仅存测试版 / 🟡 需注意（严重程度：橙 > 黄）
ATTENTION_STATUSES: tuple[Status, ...] = (Status.PRERELEASE, Status.DEGRADED)


class Verdict(str, Enum):
    """报告的一句话结论（PRD §5.4 的 8 种）。"""

    ALL_READY = "all_ready"
    READY_WITH_DEGRADED = "ready_with_degraded"
    BLOCKED = "blocked"
    INCOMPLETE = "incomplete"
    ALL_UNKNOWN = "all_unknown"
    ALL_BLOCKED = "all_blocked"
    EMPTY = "empty"
    INTERRUPTED = "interrupted"


@dataclass(slots=True)
class ReportItem:
    """报告里的一条模组记录。"""

    mod: ModEntry
    status: Status
    reason: ReasonCode
    reason_key: str
    hint_key: str
    latest_for_loader: VersionInfo | None = None
    latest_compat: VersionInfo | None = None
    latest_any: VersionInfo | None = None
    max_supported_mc: str | None = None
    available_loaders: tuple[str, ...] = ()
    current_version: str | None = None
    provider_message: str = ""

    def to_dict(self) -> dict[str, object]:
        """序列化（导出 JSON / 未来 GUI 用）。

        顶层的 key / slug / file_name 是给脚本消费的便利字段
        （否则要 dig 进 mod.sources.modrinth 两层）。
        """
        return {
            "key": self.mod.key,
            "slug": (self.mod.sources or {}).get("modrinth"),
            "file_name": self.mod.file_name,
            "mod": self.mod.to_dict(),
            "status": self.status.value,
            "reason": self.reason.value,
            "reason_key": self.reason_key,
            "hint_key": self.hint_key,
            "latest_for_loader": self.latest_for_loader.to_dict() if self.latest_for_loader else None,
            "latest_compat": self.latest_compat.to_dict() if self.latest_compat else None,
            "latest_any": self.latest_any.to_dict() if self.latest_any else None,
            "max_supported_mc": self.max_supported_mc,
            "available_loaders": list(self.available_loaders),
            "current_version": self.current_version,
            "provider_message": self.provider_message,
        }


def _empty_groups() -> dict[Status, list[ReportItem]]:
    """五个分组一个都不能少（空组不打印标题，但数据结构要在）。"""
    return {status: [] for status in GROUP_ORDER}


@dataclass(slots=True)
class Report:
    """一次完整检查的结果。"""

    mc_version: str
    loader: Loader
    profile_name: str
    generated_at: str
    elapsed: float = 0.0
    groups: dict[Status, list[ReportItem]] = field(default_factory=_empty_groups)
    warnings: list[str] = field(default_factory=list)
    source_stats: dict[SourceKind, int] = field(default_factory=dict)
    requests_made: int = 0
    cache_hits: int = 0
    interrupted: bool = False
    completed: int = 0
    total: int = 0
    profile_saved: bool = True
    #: 数据源状态文案（Modrinth / CurseForge），由 CLI 注入
    source_status: tuple[str, str] = (t("source.modrinth.enabled"),
                                      t("source.curseforge.disabled"))

    def add(self, item: ReportItem) -> None:
        """把一条结论放进对应分组。"""
        self.groups.setdefault(item.status, []).append(item)

    @property
    def summary(self) -> dict[str, int]:
        """汇总数字；两条恒等式在构造上必然成立。"""
        counted = {status: len(self.groups.get(status, [])) for status in CHECKED_STATUSES}
        ignored = len(self.groups.get(Status.IGNORED, []))
        total_checked = sum(counted.values())
        return {
            "total_all": total_checked + ignored,
            "total_checked": total_checked,
            "total": total_checked,
            "ready": counted[Status.READY],
            "degraded": counted[Status.DEGRADED],
            "prerelease": counted[Status.PRERELEASE],
            "blocked": counted[Status.BLOCKED],
            "unknown": counted[Status.UNKNOWN],
            "ignored": ignored,
        }

    def verify_identities(self) -> bool:
        """校验两条汇总恒等式（导出前与测试里自检）。"""
        data = self.summary
        first = (data["ready"] + data["degraded"] + data["prerelease"]
                 + data["blocked"] + data["unknown"] == data["total_checked"])
        second = data["total_checked"] + data["ignored"] == data["total_all"]
        return first and second

    @property
    def problem_count(self) -> int:
        """需要用户处理的问题项数量（阻塞 + 仅存测试版 + 需注意）。"""
        return sum(len(self.groups.get(status, []))
                   for status in (Status.BLOCKED, *ATTENTION_STATUSES))

    def verdict(self) -> Verdict:
        """按 PRD §5.4 给出结论类型。"""
        data = self.summary
        if self.interrupted:
            return Verdict.INTERRUPTED
        if data["total_checked"] == 0:
            return Verdict.EMPTY
        if data["blocked"] > 0:
            if data["blocked"] == data["total_checked"]:
                return Verdict.ALL_BLOCKED
            return Verdict.BLOCKED
        if data["unknown"] > 0:
            if data["unknown"] == data["total_checked"]:
                return Verdict.ALL_UNKNOWN
            return Verdict.INCOMPLETE
        if data["degraded"] > 0 or data["prerelease"] > 0:
            return Verdict.READY_WITH_DEGRADED
        return Verdict.ALL_READY

    def iter_items(self) -> Iterator[ReportItem]:
        """按分组顺序遍历全部条目（同组内保持清单原始顺序）。"""
        for status in GROUP_ORDER:
            for item in self.groups.get(status, []):
                yield item

    def to_dict(self) -> dict[str, object]:
        """导出用的完整结构。"""
        return {
            "schema_version": 1,
            "mc_version": self.mc_version,
            "loader": self.loader.value,
            "profile": self.profile_name,
            "profile_saved": self.profile_saved,
            "generated_at": self.generated_at,
            "elapsed": round(self.elapsed, 3),
            "verdict": self.verdict().value,
            "summary": self.summary,
            "requests_made": self.requests_made,
            "cache_hits": self.cache_hits,
            "interrupted": self.interrupted,
            "completed": self.completed,
            "total": self.total,
            "warnings": list(self.warnings),
            "source_stats": {kind.value: count for kind, count in self.source_stats.items()},
            "groups": {status.value: [item.to_dict() for item in self.groups.get(status, [])]
                       for status in GROUP_ORDER},
        }


def loader_display_list(loaders: Sequence[str]) -> str:
    """把加载器标识符列表变成可读的展示名列表（Forge、NeoForge）。"""
    names: list[str] = []
    for raw in loaders:
        try:
            names.append(Loader.parse(raw).display_name)
        except Exception:
            names.append(str(raw))
    return "、".join(names)


def reason_text(item: ReportItem, report: Report) -> str:
    """详情行「原因」的正文。"""
    version = item.latest_for_loader.version_number if item.latest_for_loader else ""
    loader = report.loader.display_name
    key = item.reason_key
    if key == "reason.ok":
        return t(key, loader=loader, version=version, mc=report.mc_version)
    if key == "reason.old_version_only":
        return t(key, loader=loader, version=version, mc=report.mc_version)
    if key == "reason.prerelease_only":
        return t(key, mc=report.mc_version, loader=loader)
    if key == "reason.no_loader":
        if item.available_loaders:
            return t(key, loader=loader, loaders=loader_display_list(item.available_loaders))
        return t("reason.no_loader_unknown", loader=loader)
    if key == "reason.no_mc_version":
        if item.max_supported_mc:
            return t(key, max_mc=item.max_supported_mc, mc=report.mc_version)
        return t("reason.no_mc_version_unknown", mc=report.mc_version)
    if key == "reason.error":
        return t(key, text=item.provider_message or t("err.net.generic", detail=""))
    if key == "reason.unmatched":
        return t(key)
    if key == "reason.ignored":
        return t(key)
    return t(key)


def rerun_command(report: Report) -> str:
    """报告里可直接复制的重跑命令。"""
    return "modcheck check --profile " + report.profile_name + " --mc " + report.mc_version \
        + " --loader " + report.loader.value + " --refresh"


def needs_action(item: ReportItem) -> bool:
    """该问题项是否**需要用户动手**（裁决 D43）。

    🟠/🟡 组里相当一部分其实是"你本地就是当前可用的最新版"，用户什么都不用做。
    """
    if item.status in ATTENTION_STATUSES:
        current = item.current_version
        if not current:
            return True                       # 不知道本地版本 -> 需要人工确认
        if item.reason is ReasonCode.OLD_VERSION_ONLY and item.latest_compat is not None:
            return current != item.latest_compat.version_number
        if item.reason is ReasonCode.PRERELEASE_ONLY and item.latest_for_loader is not None:
            return current != item.latest_for_loader.version_number
        return True
    return item.status in (Status.BLOCKED, Status.UNKNOWN)


def actionable_degraded(report: Report) -> int:
    """需要动作的 🟠/🟡 数量：只算真正需要用户动手的。"""
    return sum(1 for status in ATTENTION_STATUSES
               for item in report.groups.get(status, []) if needs_action(item))


def advice_text(item: ReportItem, report: Report) -> str:
    """详情行「建议」的正文。"""
    # ⚠️ 🟠 仅存测试版**不进**这个分支：它必须始终给出「这是测试版、先备份」的提醒，
    # 不能因为"本地装的就是那个测试版"就显示「无需处理」—— 那会让用户以为用它没问题。
    # 它走下面的 hint_key 分支（advice.prerelease_only）。
    if item.status is Status.DEGRADED:
        if not needs_action(item):
            return t("advice.degraded.no_action")
        if item.reason is ReasonCode.OLD_VERSION_ONLY and item.latest_compat is not None \
                and item.current_version:
            return t("advice.degraded.replace", current=item.current_version,
                     target=item.latest_compat.version_number)
    key = item.hint_key
    loader = report.loader.display_name
    if key == "advice.error":
        return t(key, command=rerun_command(report))
    if key == "advice.unmatched":
        return t(key, command="modcheck check --profile " + report.profile_name
                 + " --mc " + report.mc_version + " --loader " + report.loader.value)
    if key == "advice.no_loader":
        if item.available_loaders:
            suggest = loader_display_list(item.available_loaders[:1]) or loader
            return t(key, suggest=suggest, loader=loader)
        return t("advice.no_loader_unknown", loader=loader)
    if key == "advice.ignored":
        return t(key, profile=report.profile_name)
    return t(key)


def origin_line(report: Report) -> str:
    """报告头的「识别来源」行（四个来源一个都不能少）。"""
    stats = report.source_stats
    return t("report.header.origin",
             hash=stats.get(SourceKind.HASH, 0),
             jar_meta=stats.get(SourceKind.JAR_META, 0),
             search=stats.get(SourceKind.SEARCH, 0),
             guess=stats.get(SourceKind.FILENAME, 0))


def verdict_line(report: Report) -> str:
    """结论行（逐字，PRD §5.4）。"""
    data = report.summary
    verdict = report.verdict()
    loader = report.loader.display_name
    mc = report.mc_version
    if verdict is Verdict.INTERRUPTED:
        return t("verdict.interrupted", done=report.completed or data["total_checked"],
                 total=report.total or data["total_all"])
    if verdict is Verdict.EMPTY:
        return t("verdict.empty", name=report.profile_name)
    if verdict is Verdict.ALL_BLOCKED:
        return t("verdict.all_blocked", mc=mc, total=data["total_checked"])
    if verdict is Verdict.BLOCKED:
        return t("verdict.blocked", mc=mc, total=data["total_checked"],
                 blocked=data["blocked"], unknown=data["unknown"])
    if verdict is Verdict.ALL_UNKNOWN:
        return t("verdict.all_unknown", total=data["total_checked"])
    if verdict is Verdict.INCOMPLETE:
        return t("verdict.incomplete", mc=mc, unknown=data["unknown"])
    if verdict is Verdict.READY_WITH_DEGRADED:
        return t("verdict.ready_with_degraded", mc=mc, loader=loader,
                 ready=data["ready"], degraded=data["degraded"],
                 prerelease=data["prerelease"])
    return t("verdict.all_ready", mc=mc, loader=loader, total=data["total_checked"])


def summary_line(report: Report) -> str:
    """汇总行（含"共多少个 / 本次检查多少个"两个数）。"""
    data = report.summary
    return t("report.summary", total_all=data["total_all"], total_checked=data["total_checked"],
             ready=data["ready"], prerelease=data["prerelease"], degraded=data["degraded"],
             blocked=data["blocked"], unknown=data["unknown"], ignored=data["ignored"])


def build_action_hints(report: Report) -> list[str]:
    """报告末尾的「下一步」文本行（按实际存在的组动态生成）。"""
    data = report.summary
    lines: list[str] = []
    if data["blocked"] == 0 and actionable_degraded(report) == 0 and data["unknown"] == 0:
        lines.append(t("report.next.none"))
        return lines
    lines.append(t("report.next.title"))
    # 编号必须**动态生成**：条件跳段时用固定前缀会出现"只有 3."这种断号
    # （实测：只有 ⚪ 项时输出从 "3." 开始，用户会以为少了一步）。
    steps: list[str] = []
    if data["blocked"] > 0:
        steps.append(t("report.next.step1", index=len(steps) + 1, blocked=data["blocked"]))
    actionable = actionable_degraded(report)
    if actionable > 0:
        steps.append(t("report.next.step2", index=len(steps) + 1, degraded=actionable))
    if data["unknown"] > 0:
        steps.append(t("report.next.step3", index=len(steps) + 1, unknown=data["unknown"]))
        steps.append(t("report.next.command", profile=report.profile_name,
                       mc=report.mc_version, loader=report.loader.value))
    lines.extend(steps)
    return lines


__all__ = [
    "GROUP_ORDER", "CHECKED_STATUSES", "Verdict", "ReportItem", "Report",
    "needs_action", "actionable_degraded",
    "reason_text", "advice_text", "verdict_line", "summary_line", "origin_line",
    "build_action_hints", "loader_display_list", "rerun_command",
]
