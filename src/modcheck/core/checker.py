"""兼容性判定核心：classify() —— 本项目的心脏（PRD §4.3）。

设计原则（每一条都是实测踩出来的）：
  * **纯函数**：不联网、不排序、不读时间，输入输出都是值对象，可完全离线单测；
  * **只看数组第一个元素**：Modrinth 的 /version 已按发布时间倒序，日期会并列，
    任何"自己排序"或"取 max(date_published)"都会引入不稳定（基线 §7）；
  * **判定一律以 latest_for_loader 为准**：JourneyMap 为同一版本号发了
    paper/neoforge/forge/fabric 四条且时间完全相同，按"全局最新"判定会误判成 🟡；
  * **网络错误永远不是红色**：ERROR 一律 UNKNOWN（基线第 8 条坑）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from modcheck.core.mcversion import max_release
from modcheck.core.models import Loader, ReasonCode, Status, VersionInfo

#: 原因码 -> (原因文案 key, 建议文案 key)
REASON_KEYS: dict[ReasonCode, tuple[str, str]] = {
    ReasonCode.OK: ("reason.ok", "advice.ok"),
    ReasonCode.OK_SAME_VERSION_NUMBER: ("reason.ok_same_version", "advice.ok"),
    ReasonCode.OLD_VERSION_ONLY: ("reason.old_version_only", "advice.old_version_only"),
    ReasonCode.PRERELEASE_ONLY: ("reason.prerelease_only", "advice.prerelease_only"),
    ReasonCode.NO_LOADER: ("reason.no_loader", "advice.no_loader"),
    ReasonCode.NO_MC_VERSION: ("reason.no_mc_version", "advice.no_mc_version"),
    ReasonCode.NOT_FOUND: ("reason.not_found", "advice.not_found"),
    ReasonCode.NO_FILES: ("reason.no_files", "advice.no_files"),
    ReasonCode.ERROR: ("reason.error", "advice.error"),
    ReasonCode.UNMATCHED: ("reason.unmatched", "advice.unmatched"),
    ReasonCode.IGNORED: ("reason.ignored", "advice.ignored"),
    ReasonCode.MC_VERSION_FUZZY: ("reason.ok", "advice.ok"),  # 预留，本期不产生
}


@dataclass(frozen=True, slots=True)
class Classification:
    """一次判定的完整结果（纯数据）。"""

    status: Status
    reason: ReasonCode
    reason_key: str
    hint_key: str
    latest_for_loader: VersionInfo | None = None
    latest_compat: VersionInfo | None = None
    latest_any: VersionInfo | None = None
    max_supported_mc: str | None = None
    available_loaders: tuple[str, ...] = ()


def _first(versions: Sequence[VersionInfo]) -> VersionInfo | None:
    """取数组第一条 —— 唯一允许的"取最新"方式。"""
    return versions[0] if versions else None


def _supports(version: VersionInfo, mc_version: str, loader: Loader) -> bool:
    """版本本身是否支持"目标 MC 版本 + 目标加载器"。

    判定规则只做字符串精确包含（不做高低比较，见基线 §7）。
    """
    return mc_version in version.game_versions and loader.value in version.loaders


def _usable(version: VersionInfo, prerelease: bool) -> bool:
    """该版本能否计入"最新版"：--pre 之前只认正式版通道。"""
    return prerelease or version.is_release


def classify(*, loader: Loader, mc_version: str,
             releases_for_loader: Sequence[VersionInfo] = (),
             compat_releases: Sequence[VersionInfo] = (),
             compat_any: Sequence[VersionInfo] = (),
             any_for_loader: Sequence[VersionInfo] = (),
             prerelease: bool = False,
             version_count: int | None = None,
             available_loaders: Sequence[str] = ()) -> Classification:
    """按 PRD §4.3 的六分支判定一个模组。

    参数：
        loader: 目标服务端加载器。
        mc_version: 目标 MC 版本（字符串精确包含，不做高低比较）。
        releases_for_loader: 请求 A —— 目标加载器的最新正式版（已按时间倒序）。
        compat_releases: 请求 B —— 目标加载器 + 目标 MC 的最新正式版。
        compat_any: 请求 B2 —— 仅在 B 为空时发起，放宽到 beta/alpha。
        any_for_loader: 请求 A2 —— 仅在 A 为空时发起，判断"完全没有该加载器"还是"只有测试版"。
        prerelease: --pre 时为真，此时 A/B 已是不过滤通道的列表。
        version_count: 项目的版本总数；仅用于区分 🔴 NO_FILES 与 🔴 NO_LOADER。
        available_loaders: 项目实际发布的加载器（供 NO_LOADER 文案使用）。

    返回：
        Classification（状态 + 原因码 + 展示需要的版本对象）。
    """
    latest_loader = _first(releases_for_loader)
    latest_compat = _first(compat_releases)
    latest_any = _first(compat_any) if (not compat_releases and compat_any) else None

    # ① 目标加载器下什么都没有
    if latest_loader is None and not any_for_loader:
        if version_count == 0:
            return _result(Status.BLOCKED, ReasonCode.NO_FILES, available_loaders=available_loaders)
        return _result(Status.BLOCKED, ReasonCode.NO_LOADER, available_loaders=available_loaders)

    # ② A 为空但 A2 非空 -> 该加载器只有 beta/alpha，继续判断 ④⑤
    #
    # ③ 目标加载器的最新版本身就支持 V。
    # ⚠️ 这里**不能**只比 version_id：那样等于完全信任调用方传来的 compat_releases。
    # 一旦编排层传错（最容易的是把 A2 当成 B 传进来），就会把"最新版不支持 V"
    # 判成 READY —— 那正是 PRD §1.3 的第一红线（误报为绿，服主升级后服务器崩）。
    # 所以这里**自己验一遍** A[0]：它就是 latest_for_loader 的定义。
    if latest_loader is not None and _usable(latest_loader, prerelease) \
            and _supports(latest_loader, mc_version, loader):
        return _result(Status.READY, ReasonCode.OK,
                       latest_for_loader=latest_loader, latest_compat=latest_loader)
    # ③b（裁决 D40）：最新版与"目标 MC 上能用的那个版本"**版本号相同**时算 🟢。
    # 实测样例：entityculling 目标 26.1，最新版 1.11.2 支持 26.3，兼容版 1.11.2 支持 26.1 ——
    # 版本号一样却报"最新版不支持 / 可用 1.11.2"，自相矛盾，用户会以为工具坏了。
    # ⚠️ 三个条件缺一不可：版本号相同 **且** 那个版本真的支持目标 MC（自校验，
    # 否则调用方传错就会"误报为绿"）**且** 双方都在允许的通道内。
    if latest_loader is not None and latest_compat is not None \
            and latest_compat.version_number == latest_loader.version_number \
            and _supports(latest_compat, mc_version, loader) \
            and _usable(latest_compat, prerelease) and _usable(latest_loader, prerelease):
        return _result(Status.READY, ReasonCode.OK_SAME_VERSION_NUMBER,
                       latest_for_loader=latest_loader, latest_compat=latest_compat)
    # ④ 有兼容的正式版，但不是最新版（同样自己验一遍 B[0] 是否真的支持 V）
    if latest_compat is not None and _supports(latest_compat, mc_version, loader):
        return _result(Status.DEGRADED, ReasonCode.OLD_VERSION_ONLY,
                       latest_for_loader=latest_loader, latest_compat=latest_compat)
    # ⑤ 正式版都不支持，但放宽通道后支持 -> 只有测试版能用
    if not prerelease and latest_any is not None:
        return _result(Status.PRERELEASE, ReasonCode.PRERELEASE_ONLY,
                       latest_for_loader=latest_loader, latest_any=latest_any)
    # ⑥ 该加载器有文件，但都不支持 V
    supported = [gv for version in (releases_for_loader or any_for_loader)
                 for gv in version.game_versions]
    return _result(Status.BLOCKED, ReasonCode.NO_MC_VERSION,
                   latest_for_loader=latest_loader, max_supported_mc=max_release(supported))


def _result(status: Status, reason: ReasonCode, *,
            latest_for_loader: VersionInfo | None = None,
            latest_compat: VersionInfo | None = None,
            latest_any: VersionInfo | None = None,
            max_supported_mc: str | None = None,
            available_loaders: Sequence[str] = ()) -> Classification:
    """按原因码补齐文案 key，避免每个分支重复写字符串。"""
    reason_key, hint_key = REASON_KEYS[reason]
    return Classification(
        status=status, reason=reason, reason_key=reason_key, hint_key=hint_key,
        latest_for_loader=latest_for_loader, latest_compat=latest_compat,
        latest_any=latest_any, max_supported_mc=max_supported_mc,
        available_loaders=tuple(available_loaders),
    )


def for_reason(reason: ReasonCode, *, status: Status | None = None,
               available_loaders: Sequence[str] = ()) -> Classification:
    """构造"非版本判定"的结论：项目不存在 / 网络错误 / 未匹配 / 已忽略。"""
    default_status = {
        ReasonCode.NOT_FOUND: Status.BLOCKED,
        ReasonCode.NO_FILES: Status.BLOCKED,
        ReasonCode.ERROR: Status.UNKNOWN,
        ReasonCode.UNMATCHED: Status.UNKNOWN,
        ReasonCode.IGNORED: Status.IGNORED,
    }.get(reason, Status.UNKNOWN)
    return _result(status or default_status, reason, available_loaders=available_loaders)


__all__ = ["Classification", "classify", "for_reason", "REASON_KEYS"]
