"""扫描结果落盘（flows/scan_flow.save_scan_result）的单测。

这段逻辑原本在 cli/commands/scan.py 的 run_scan 里；下沉到流程层是为了 GUI 三期
（扫描 UI）能复用同一条"合并 + 原子写盘"，所以这里断言的是**行为契约**：
新建 / 合并 / --new 替换 / 取消绝不落盘 / 写盘失败磁盘不变 / 提示的时机。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from fakes import FakeProvider
from modcheck.core.models import MatchStatus, ModEntry, ProjectHit
from modcheck.errors import ConfigError, ProfileError, UserCancelled
from modcheck.flows.scan_flow import ScanReport, save_scan_result, scan_dirs

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_fixtures  # noqa: E402


def make_entry(key: str, *, name: str = "", file_name: str = "") -> ModEntry:
    """造一条清单记录。"""
    return ModEntry(key=key, display_name=name or key, mod_id=key, file_name=file_name,
                    sources={"modrinth": key})


def make_scan(*entries: ModEntry, cancelled: bool = False) -> ScanReport:
    """造一份扫描结果。"""
    return ScanReport(entries=list(entries), cancelled=cancelled)


def read_mods(path: Path) -> list[str]:
    """读回清单里的 key 列表（顺序敏感）。

    注意 key 不是我们传进去的那个字符串：storage.key_of 会把
    "有平台项目"的记录统一成 slug:<provider>:<slug>（决策 D30）。
    """
    return [item["key"] for item in json.loads(path.read_text(encoding="utf-8"))["mods"]]


def key_of(name: str) -> str:
    """与 storage.key_of 一致的稳定键。"""
    return "slug:modrinth:" + name


# ---------------------------------------------------------------- 新建 / 合并
def test_new_profile_is_created_with_notice(tmp_path: Path) -> None:
    """清单不存在：创建 + 回调一次"将新建一个"（CLI 靠它打印那句）。"""
    profiles = tmp_path / "profiles"
    notices: list[tuple] = []
    outcome = save_scan_result(make_scan(make_entry("carpet"), make_entry("lithium")),
                               profiles_dir=profiles, profile_name="demo",
                               on_notice=lambda key, **kw: notices.append((key, kw)))
    assert outcome.created is True and outcome.replaced is False
    assert outcome.path == profiles / "demo.json"
    assert outcome.path.exists()
    assert outcome.stats.added == 2 and outcome.stats.merged == 0
    assert len(outcome.merged) == 2
    assert read_mods(outcome.path) == [key_of("carpet"), key_of("lithium")]
    assert notices == [("scan.profile_not_exist", {"name": "demo"})]


def test_notice_fires_before_the_file_is_written(tmp_path: Path) -> None:
    """提示必须发生在写盘**之前** —— CLI 的逐字输出顺序靠这个位置。"""
    profiles = tmp_path / "profiles"
    seen: list[bool] = []
    save_scan_result(make_scan(make_entry("carpet")), profiles_dir=profiles,
                     profile_name="demo",
                     on_notice=lambda key, **kw: seen.append((profiles / "demo.json").exists()))
    assert seen == [False]


def test_existing_profile_is_merged(tmp_path: Path) -> None:
    """已有清单：新条目合并进去，老条目一个都不能丢，且不再提示"将新建"。"""
    profiles = tmp_path / "profiles"
    first = save_scan_result(make_scan(make_entry("carpet", file_name="carpet-26.1.jar")),
                             profiles_dir=profiles, profile_name="demo")
    notices: list[tuple] = []
    second = save_scan_result(make_scan(make_entry("lithium")), profiles_dir=profiles,
                              profile_name="demo",
                              on_notice=lambda key, **kw: notices.append((key, kw)))
    assert first.created is True and second.created is False
    assert notices == []
    assert second.stats.added == 1
    assert read_mods(second.path) == [key_of("carpet"), key_of("lithium")]
    assert second.path.exists()


def test_same_entry_twice_is_merged_not_duplicated(tmp_path: Path) -> None:
    """同一条记录扫描两次：合并（幂等），不会变成两条。"""
    profiles = tmp_path / "profiles"
    save_scan_result(make_scan(make_entry("carpet")), profiles_dir=profiles,
                     profile_name="demo")
    outcome = save_scan_result(make_scan(make_entry("carpet")), profiles_dir=profiles,
                               profile_name="demo")
    assert read_mods(outcome.path) == [key_of("carpet")]
    assert outcome.stats.merged == 1


def test_new_flag_replaces_existing_profile(tmp_path: Path) -> None:
    """--new：整份替换（旧条目清掉、created_at 重来），但仍然不提示"将新建"。"""
    profiles = tmp_path / "profiles"
    save_scan_result(make_scan(make_entry("carpet")), profiles_dir=profiles,
                     profile_name="demo")
    before = json.loads((profiles / "demo.json").read_text(encoding="utf-8"))["created_at"]
    notices: list[tuple] = []
    outcome = save_scan_result(make_scan(make_entry("lithium")), profiles_dir=profiles,
                               profile_name="demo", new=True,
                               on_notice=lambda key, **kw: notices.append((key, kw)))
    assert outcome.replaced is True and outcome.created is False
    assert notices == []
    assert read_mods(outcome.path) == [key_of("lithium")]


def test_new_flag_on_missing_profile_still_notices(tmp_path: Path) -> None:
    """--new 且文件不存在：同样是"将新建一个"。"""
    notices: list[tuple] = []
    outcome = save_scan_result(make_scan(make_entry("carpet")),
                               profiles_dir=tmp_path / "profiles", profile_name="demo",
                               new=True,
                               on_notice=lambda key, **kw: notices.append((key, kw)))
    assert outcome.created is True and notices[0][0] == "scan.profile_not_exist"


def test_duplicate_file_warning_is_surfaced(tmp_path: Path) -> None:
    """同名两文件必须给出告警（会让服务器启动失败的真实事故）。"""
    profiles = tmp_path / "profiles"
    save_scan_result(make_scan(make_entry("carpet", file_name="a.jar")),
                     profiles_dir=profiles, profile_name="demo")
    outcome = save_scan_result(make_scan(make_entry("carpet", file_name="b.jar")),
                               profiles_dir=profiles, profile_name="demo")
    assert outcome.stats.warnings


# ---------------------------------------------------------------- 取消 / 失败
def test_cancelled_report_is_never_written(tmp_path: Path) -> None:
    """取消的扫描结果绝不落盘（半份清单比没有清单更危险）。"""
    profiles = tmp_path / "profiles"
    with pytest.raises(UserCancelled):
        save_scan_result(make_scan(make_entry("carpet"), cancelled=True),
                         profiles_dir=profiles, profile_name="demo")
    assert not profiles.exists()


def test_cancelled_report_leaves_existing_profile_untouched(tmp_path: Path) -> None:
    """已有清单时取消：文件字节不变（不能悄悄改窄用户的清单）。"""
    profiles = tmp_path / "profiles"
    save_scan_result(make_scan(make_entry("carpet")), profiles_dir=profiles,
                     profile_name="demo")
    before = (profiles / "demo.json").read_bytes()
    with pytest.raises(UserCancelled):
        save_scan_result(make_scan(make_entry("lithium"), cancelled=True),
                         profiles_dir=profiles, profile_name="demo")
    assert (profiles / "demo.json").read_bytes() == before


def test_write_failure_keeps_disk_unchanged(tmp_path: Path) -> None:
    """写盘失败：抛 ProfileError，磁盘上的旧文件保持原样（还有内存里的也不变）。"""
    profiles = tmp_path / "profiles"
    save_scan_result(make_scan(make_entry("carpet")), profiles_dir=profiles,
                     profile_name="demo")
    before = (profiles / "demo.json").read_bytes()

    import modcheck.flows.scan_flow as flow_module

    def refuse(profile, path):
        raise ProfileError("磁盘满")

    original = flow_module.save_profile
    flow_module.save_profile = refuse
    try:
        with pytest.raises(ProfileError):
            save_scan_result(make_scan(make_entry("lithium")), profiles_dir=profiles,
                             profile_name="demo")
    finally:
        flow_module.save_profile = original
    assert (profiles / "demo.json").read_bytes() == before


def test_invalid_profile_name_is_rejected(tmp_path: Path) -> None:
    """非法清单名 -> ConfigError（不写盘）。"""
    with pytest.raises(ConfigError):
        save_scan_result(make_scan(make_entry("carpet")),
                         profiles_dir=tmp_path / "profiles", profile_name="a/b")


# ---------------------------------------------------------------- 与真扫描串起来
def test_scan_then_save_end_to_end(tmp_path: Path) -> None:
    """真扫描 + 落盘：条目来自 jar（指纹/元数据/搜索），写出的清单能读回来。"""
    mods = make_fixtures.make_mods_dir(tmp_path / "mods")
    provider = FakeProvider(hits=[ProjectHit("Pcarpet", "carpet", "Carpet", 1, "d", "fake"),
                                  ProjectHit("Papi", "fabric-api", "Fabric API", 1, "d", "f"),
                                  ProjectHit("Pli", "lithium", "Lithium", 1, "d", "fake")])
    report = scan_dirs([mods], provider=provider)
    outcome = save_scan_result(report, profiles_dir=tmp_path / "profiles", profile_name="demo")
    assert outcome.created is True
    assert len(outcome.merged) == len(report.entries)
    saved = json.loads(outcome.path.read_text(encoding="utf-8"))
    assert saved["name"] == "demo"
    assert len(saved["mods"]) == len(report.entries)
    assert all(item["key"] for item in saved["mods"])


def test_saved_entries_keep_match_status(tmp_path: Path) -> None:
    """落盘不能把匹配状态丢掉（🟢/🟡 的判定与忽略开关都靠它）。"""
    entry = ModEntry(key="carpet", display_name="Carpet", mod_id="carpet",
                     sources={"modrinth": "carpet"}, match_status=MatchStatus.IGNORED)
    outcome = save_scan_result(make_scan(entry), profiles_dir=tmp_path / "profiles",
                               profile_name="demo")
    saved = json.loads(outcome.path.read_text(encoding="utf-8"))
    assert saved["mods"][0]["match_status"] == "ignored"
