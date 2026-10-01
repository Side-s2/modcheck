"""T-09 classify() 测试：六分支 + 基线 §17.3 的 5 条真实断言。

这里的数据结构是照着 Modrinth 真实响应构造的（字段名与实测一致），
日期一律照抄实测值；**判定只允许看数组第一条**，所以顺序即事实。
"""
from __future__ import annotations

import pytest

from modcheck.core.checker import Classification, classify, for_reason
from modcheck.core.models import FileInfo, Loader, ReasonCode, Status, VersionInfo


def V(vid: str, number: str, *, mc: tuple[str, ...] = (), loaders: tuple[str, ...] = ("fabric",),
      vtype: str = "release", date: str = "2026-09-19T00:00:00Z") -> VersionInfo:
    """构造一个版本条目（默认 fabric 正式版）。"""
    return VersionInfo(
        version_id=vid, version_number=number, name=number, project_id="P",
        date_published=date, version_type=vtype, game_versions=mc, loaders=loaders,
        files=(FileInfo(filename="f.jar", url="u", primary=True, size=1, hashes={}),),
    )


# ---------------------------------------------------------------- 六分支
def test_branch_no_loader() -> None:
    """① 目标加载器完全没有文件 -> 🔴 NO_LOADER（create 只有 Forge/NeoForge）。"""
    result = classify(loader=Loader.FABRIC, mc_version="26.3",
                      releases_for_loader=[], compat_releases=[], compat_any=[],
                      any_for_loader=[], version_count=42,
                      available_loaders=("forge", "neoforge"))
    assert result.status is Status.BLOCKED
    assert result.reason is ReasonCode.NO_LOADER
    assert result.available_loaders == ("forge", "neoforge")
    assert result.reason_key == "reason.no_loader"
    assert result.hint_key == "advice.no_loader"


def test_branch_no_files() -> None:
    """①b 项目存在但一个文件都没有 -> 🔴 NO_FILES（独立码，不得复用 NO_LOADER）。"""
    result = classify(loader=Loader.FABRIC, mc_version="26.3", version_count=0)
    assert result.status is Status.BLOCKED
    assert result.reason is ReasonCode.NO_FILES
    assert result.reason is not ReasonCode.NO_LOADER


def test_branch_ready() -> None:
    """③ 目标加载器最新正式版就支持 V -> 🟢 OK。"""
    latest = V("V26", "26.3", mc=("26.3",))
    result = classify(loader=Loader.FABRIC, mc_version="26.3",
                      releases_for_loader=[latest], compat_releases=[latest])
    assert result.status is Status.READY
    assert result.reason is ReasonCode.OK
    assert result.latest_for_loader is latest


def test_branch_old_version_only() -> None:
    """④ 有兼容正式版但不是最新版 -> 🟡 OLD_VERSION_ONLY。"""
    newest = V("V26", "26.3", mc=("26.3",))
    older = V("V21", "26.1", mc=("26.1",))
    result = classify(loader=Loader.FABRIC, mc_version="26.1",
                      releases_for_loader=[newest], compat_releases=[older])
    assert result.status is Status.DEGRADED
    assert result.reason is ReasonCode.OLD_VERSION_ONLY
    assert result.latest_compat is older


def test_branch_prerelease_only() -> None:
    """⑤ 正式版都不支持，只有测试版 -> 🟡 PRERELEASE_ONLY。"""
    newest = V("V31", "31.8.0.49", mc=("26.3",))
    beta = V("V31b", "31.8.0.49", mc=("26.3",), vtype="beta")
    result = classify(loader=Loader.FABRIC, mc_version="26.3",
                      releases_for_loader=[newest], compat_releases=[], compat_any=[beta])
    assert result.status is Status.DEGRADED
    assert result.reason is ReasonCode.PRERELEASE_ONLY
    assert result.latest_any is beta


def test_branch_no_mc_version() -> None:
    """⑥ 有该加载器的文件但都不支持 V -> 🔴 NO_MC_VERSION + max_supported_mc。"""
    old = V("V1", "6.0.8.1", mc=("1.20.1", "1.20.2"))
    result = classify(loader=Loader.FABRIC, mc_version="26.3",
                      releases_for_loader=[old], compat_releases=[], compat_any=[])
    assert result.status is Status.BLOCKED
    assert result.reason is ReasonCode.NO_MC_VERSION
    assert result.max_supported_mc == "1.20.2"


def test_prerelease_flag_never_yields_prerelease_only() -> None:
    """--pre 时 A/B 已经不过滤通道，不会再产生 PRERELEASE_ONLY。"""
    newest = V("V", "31.8.0.49", mc=("26.3",), vtype="beta")
    result = classify(loader=Loader.FABRIC, mc_version="26.3",
                      releases_for_loader=[newest], compat_releases=[newest], prerelease=True)
    assert result.status is Status.READY
    assert result.reason is ReasonCode.OK


def test_error_is_unknown_never_blocked() -> None:
    """网络错误一律 ⚪ UNKNOWN，绝不是红色（第 1 条红线）。"""
    result = for_reason(ReasonCode.ERROR)
    assert result.status is Status.UNKNOWN
    assert result.reason is ReasonCode.ERROR
    assert result.status is not Status.BLOCKED
    unmatched = for_reason(ReasonCode.UNMATCHED)
    assert unmatched.status is Status.UNKNOWN
    not_found = for_reason(ReasonCode.NOT_FOUND)
    assert not_found.status is Status.BLOCKED


# ---------------------------------------------------------------- 基线 §17.3 五条真实断言
def test_gt_carpet_261_fabric() -> None:
    """carpet @ 26.1/fabric -> 🟡 OLD_VERSION_ONLY（最新 fabric 版是 26.3）。"""
    v263 = V("c263", "26.3", mc=("26.3",), date="2026-09-18T10:00:00Z")
    v261 = V("c261", "26.1", mc=("26.1",), date="2026-04-02T10:00:00Z")
    result = classify(loader=Loader.FABRIC, mc_version="26.1",
                      releases_for_loader=[v263], compat_releases=[v261])
    assert (result.status, result.reason) == (Status.DEGRADED, ReasonCode.OLD_VERSION_ONLY)
    assert result.latest_compat is not None and result.latest_compat.version_number == "26.1"


def test_gt_carpet_263_fabric() -> None:
    """carpet @ 26.3/fabric -> 🟢 OK。"""
    v263 = V("c263", "26.3", mc=("26.3",))
    result = classify(loader=Loader.FABRIC, mc_version="26.3",
                      releases_for_loader=[v263], compat_releases=[v263])
    assert (result.status, result.reason) == (Status.READY, ReasonCode.OK)


def test_gt_journeymap_263_fabric() -> None:
    """journeymap @ 26.3/fabric -> 🟢 OK。

    回归重点：作者为同一版本号发了 paper/neoforge/forge/fabric 四条，
    发布时间完全相同（2026-09-19）。若按"全局最新"判定会拿到 +paper 那条，
    把本该 🟢 的模组误判成 🟡。
    """
    same_date = "2026-09-19T12:00:00Z"
    fabric = V("jm-f", "26.3-6.0.9+fabric", mc=("26.3",), loaders=("fabric",), date=same_date)
    result = classify(loader=Loader.FABRIC, mc_version="26.3",
                      releases_for_loader=[fabric], compat_releases=[fabric])
    assert (result.status, result.reason) == (Status.READY, ReasonCode.OK)


def test_gt_journeymap_wrong_input_would_misjudge() -> None:
    """反证：如果调用方不按加载器过滤（把 paper 那条当最新），就会误判成 🟡。"""
    same_date = "2026-09-19T12:00:00Z"
    paper = V("jm-p", "26.3-6.0.9+paper", mc=("26.3",), loaders=("paper",), date=same_date)
    fabric = V("jm-f", "26.3-6.0.9+fabric", mc=("26.3",), loaders=("fabric",), date=same_date)
    result = classify(loader=Loader.FABRIC, mc_version="26.3",
                      releases_for_loader=[paper], compat_releases=[fabric])
    assert (result.status, result.reason) == (Status.DEGRADED, ReasonCode.OLD_VERSION_ONLY)


def test_gt_jei_261_fabric() -> None:
    """jei @ 26.1/fabric -> 🟡 OLD_VERSION_ONLY（最新 31.8.0.49 不支持 26.1）。"""
    newest = V("j31", "31.8.0.49", mc=("26.3",))
    compat = V("j29", "29.34.0.90", mc=("26.1",))
    result = classify(loader=Loader.FABRIC, mc_version="26.1",
                      releases_for_loader=[newest], compat_releases=[compat])
    assert (result.status, result.reason) == (Status.DEGRADED, ReasonCode.OLD_VERSION_ONLY)
    assert result.latest_compat is not None
    assert result.latest_compat.version_number == "29.34.0.90"


def test_gt_jei_263_fabric() -> None:
    """jei @ 26.3/fabric -> 🟡 PRERELEASE_ONLY（release 通道无兼容版本，beta 有）。"""
    newest = V("j31", "31.8.0.49", mc=("26.3",))
    beta = V("j31b", "31.8.0.49", mc=("26.3",), vtype="beta")
    result = classify(loader=Loader.FABRIC, mc_version="26.3",
                      releases_for_loader=[newest], compat_releases=[], compat_any=[beta])
    assert (result.status, result.reason) == (Status.DEGRADED, ReasonCode.PRERELEASE_ONLY)


# ---------------------------------------------------------------- 防"自行排序"
def test_only_first_element_is_used() -> None:
    """只准看数组第一条：把"更新的"放在后面也不会被选中。"""
    first = V("V1", "1.0", mc=("1.20.1",), date="2020-01-01T00:00:00Z")
    later_date_but_second = V("V2", "2.0", mc=("26.3",), date="2030-01-01T00:00:00Z")
    result = classify(loader=Loader.FABRIC, mc_version="26.3",
                      releases_for_loader=[first, later_date_but_second],
                      compat_releases=[])
    assert result.status is Status.BLOCKED
    assert result.reason is ReasonCode.NO_MC_VERSION
    assert result.latest_for_loader is first


def test_classification_is_frozen_and_typed() -> None:
    """Classification 是值对象，且默认值齐全。"""
    result = for_reason(ReasonCode.IGNORED)
    assert isinstance(result, Classification)
    assert result.status is Status.IGNORED
    with pytest.raises(Exception):
        result.status = Status.READY  # type: ignore[misc]
