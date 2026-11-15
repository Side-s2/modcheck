"""导入模组清单（flows.export.import_modlist）的单测。

这段功能是「导出模组清单」的逆操作：读别人导出的 JSON 清单 -> 校验 -> 合并进本机清单。
所以这里断言的是**行为契约**：

  * 导出的清单必须能原样导回来（含中文名、平台项目）；
  * 合并规则与扫描落盘是同一份（复用 flows.scan_flow.save_scan_result）；
  * 每一种"不像本工具的清单"都给出能读懂的中文说明，而不是把异常抛给用户；
  * 任何一条错误路径都不许改动磁盘上的清单（要么成，要么什么都没发生）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modcheck.core.models import ModEntry, Profile, Settings
from modcheck.errors import ProfileError
from modcheck.flows.export import (MODLIST_SCHEMA_VERSION, export_modlist, import_modlist,
                                   read_modlist)
from modcheck.storage.profiles import load_profile, new_profile, profile_path, save_profile


# ---------------------------------------------------------------- 造数据
def entry(key: str, **kw: object) -> ModEntry:
    """一条"已匹配到 Modrinth 项目"的记录。"""
    values: dict = {"display_name": key, "mod_id": key, "sources": {"modrinth": key}}
    values.update(kw)
    return ModEntry(key=key, **values)          # type: ignore[arg-type]


def make_profile(name: str, *mods: ModEntry) -> Profile:
    """一份清单（不落盘）。"""
    profile = new_profile(name)
    profile.mods = list(mods)
    return profile


def export_to(tmp_path: Path, profile: Profile, name: str = "modlist_对方.json") -> Path:
    """用**真正的导出功能**造一份清单文件（保证"导出的能被导回来"是被验证过的）。"""
    target = tmp_path / name
    export_modlist(profile, target)
    return target


def write_json(path: Path, raw: object) -> Path:
    """手写一份（合法或不合法的）JSON 文件。"""
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return path


def keys_of(path: Path) -> list[str]:
    """读回清单里的 key 列表（顺序敏感）。"""
    return [item["key"] for item in json.loads(Path(path).read_text(encoding="utf-8"))["mods"]]


# ---------------------------------------------------------------- 导入：新建 / 合并
def test_export_then_import_creates_new_profile(tmp_path: Path) -> None:
    """导出 -> 导入：条目一个不少地落进新清单（作者要的就是这条路径）。"""
    source = export_to(tmp_path, make_profile(
        "服务器B", entry("carpet", cn_name="地毯", file_name="carpet-26.1.jar"),
        entry("lithium", file_name="lithium-0.12.jar")))
    outcome = import_modlist(source, profiles_dir=tmp_path / "profiles", profile_name="服务器B")

    assert outcome.created is True and outcome.imported == 2
    assert outcome.stats.added == 2 and outcome.stats.merged == 0
    assert outcome.source == source
    saved = load_profile(outcome.path)
    assert saved.name == "服务器B"
    assert [item.sources.get("modrinth") for item in saved.mods] == ["carpet", "lithium"]
    assert saved.mods[0].cn_name == "地毯"          # 中文名不能被导入丢掉
    assert saved.mods[0].file_name == "carpet-26.1.jar"


def test_import_merges_into_existing_profile(tmp_path: Path) -> None:
    """已有清单：新条目并进去、同一条记录按 key 合并（不是变成两条）。"""
    profiles = tmp_path / "profiles"
    save_profile(make_profile("demo", entry("carpet", file_name="carpet-25.jar")),
                 profile_path(profiles, "demo"))
    source = export_to(tmp_path, make_profile(
        "朋友的服务端", entry("carpet", file_name="carpet-26.1.jar"), entry("sodium")))

    outcome = import_modlist(source, profiles_dir=profiles, profile_name="demo")

    assert outcome.created is False and outcome.imported == 2
    assert outcome.stats.added == 1 and outcome.stats.merged == 1
    assert keys_of(outcome.path) == ["slug:modrinth:carpet", "slug:modrinth:sodium"]
    # 同一模组的两个 jar 必须显式告警（会让服务器启动失败的真实事故）
    assert outcome.stats.warnings
    assert "carpet-26.1.jar" in outcome.stats.warnings[0]


def test_import_merges_by_file_name_when_keys_differ(tmp_path: Path) -> None:
    """合并规则与扫描落盘**同一份**：key 对不上时仍按 slug / sha1 / 文件名 认同一条记录。"""
    profiles = tmp_path / "profiles"
    save_profile(make_profile("demo", ModEntry(key="unknown-thing", display_name="Unknown",
                                               file_name="mystery-1.0.jar")),
                 profile_path(profiles, "demo"))
    source = export_to(tmp_path, make_profile(
        "对方的清单", ModEntry(key="mystery", display_name="Mystery",
                               file_name="mystery-1.0.jar")))

    outcome = import_modlist(source, profiles_dir=profiles, profile_name="demo")

    assert len(outcome.merged) == 1                 # 同一份文件 -> 同一条记录，没有重复
    assert outcome.stats.merged == 1 and outcome.stats.added == 0


def test_import_twice_is_idempotent(tmp_path: Path) -> None:
    """同一份清单导入两次：第二次只合并、不新增（清单不会越导越长）。"""
    source = export_to(tmp_path, make_profile("B", entry("carpet", file_name="carpet.jar")))
    profiles = tmp_path / "profiles"
    first = import_modlist(source, profiles_dir=profiles, profile_name="B")
    second = import_modlist(source, profiles_dir=profiles, profile_name="B")

    assert first.stats.added == 1
    assert second.stats.added == 0 and second.stats.merged == 1
    assert keys_of(second.path) == ["slug:modrinth:carpet"]


def test_notice_fires_only_when_the_profile_is_missing(tmp_path: Path) -> None:
    """「不存在名为 X 的清单，将新建一个」只在该说的时候说（与扫描落盘用同一句）。"""
    source = export_to(tmp_path, make_profile("B", entry("carpet")))
    profiles = tmp_path / "profiles"
    notices: list[tuple] = []
    note = lambda key, **kw: notices.append((key, kw))       # noqa: E731

    import_modlist(source, profiles_dir=profiles, profile_name="B", on_notice=note)
    assert notices == [("scan.profile_not_exist", {"name": "B"})]

    notices.clear()
    import_modlist(source, profiles_dir=profiles, profile_name="B", on_notice=note)
    assert notices == []


def test_empty_modlist_is_allowed(tmp_path: Path) -> None:
    """0 个模组的清单是合法的（对方确实可能导出过一份空清单）。"""
    source = export_to(tmp_path, make_profile("空清单"))
    outcome = import_modlist(source, profiles_dir=tmp_path / "profiles", profile_name="空清单")
    assert outcome.created is True and outcome.imported == 0
    assert load_profile(outcome.path).mods == []


def test_import_accepts_a_profile_object(tmp_path: Path) -> None:
    """CLI 已经读好 Profile 时不必重读文件（屏幕先预览、后导入走的就是这条路）。"""
    profile = read_modlist(export_to(tmp_path, make_profile("B", entry("carpet"))))
    outcome = import_modlist(profile, profiles_dir=tmp_path / "profiles", profile_name="B")
    assert outcome.source is None and outcome.imported == 1


# ---------------------------------------------------------------- 校验：非法输入
def test_invalid_json_is_reported_in_chinese(tmp_path: Path) -> None:
    """语法坏掉的 JSON：说清是哪个文件、坏在哪，并指出该找什么文件。"""
    bad = tmp_path / "bad.json"
    bad.write_text('{"mods": [', encoding="utf-8")

    with pytest.raises(ProfileError) as excinfo:
        read_modlist(bad)

    message = excinfo.value.message
    assert "不是有效的 JSON" in message and str(bad) in message
    assert "导出模组清单" in message                 # 告诉用户下一步该怎么办
    assert "Traceback" not in message


def test_missing_mods_field_is_reported(tmp_path: Path) -> None:
    """缺 mods 字段 = 不是本工具的清单（参考 E12 的处理方式）。"""
    bad = write_json(tmp_path / "report.json", {"schema_version": 1, "items": []})
    with pytest.raises(ProfileError) as excinfo:
        read_modlist(bad)
    assert "未找到「mods」字段" in excinfo.value.message
    assert "不是本工具的模组清单" in excinfo.value.message


def test_mods_must_be_a_list(tmp_path: Path) -> None:
    """mods 不是列表：说清"应为列表、实际是对象"。"""
    bad = write_json(tmp_path / "bad.json", {"schema_version": 1, "mods": {"carpet": 1}})
    with pytest.raises(ProfileError) as excinfo:
        read_modlist(bad)
    assert "「mods」应为列表" in excinfo.value.message
    assert "对象" in excinfo.value.message


def test_schema_version_mismatch_is_reported(tmp_path: Path) -> None:
    """格式版本比本程序新：两个版本号都要写出来（否则用户不知道该升哪个）。"""
    future = MODLIST_SCHEMA_VERSION + 1
    bad = write_json(tmp_path / "future.json", {"schema_version": future, "mods": []})
    with pytest.raises(ProfileError) as excinfo:
        read_modlist(bad)
    message = excinfo.value.message
    assert "格式版本" in message
    assert str(future) in message and str(MODLIST_SCHEMA_VERSION) in message


def test_schema_version_boolean_is_not_an_integer(tmp_path: Path) -> None:
    """JSON 的 true 在 Python 里是 int 的子类 —— 不能当成版本号 1 放过去。"""
    bad = write_json(tmp_path / "bad.json", {"schema_version": True, "mods": []})
    with pytest.raises(ProfileError) as excinfo:
        read_modlist(bad)
    assert "应为整数" in excinfo.value.message
    assert "布尔值" in excinfo.value.message


def test_schema_version_may_be_absent(tmp_path: Path) -> None:
    """没写版本号时按当前版本处理（与 load_profile 的宽容度一致）。"""
    path = write_json(tmp_path / "minimal.json",
                      {"name": "B", "mods": [{"display_name": "Carpet"}]})
    profile = read_modlist(path)
    assert profile.schema_version == MODLIST_SCHEMA_VERSION
    assert len(profile.mods) == 1


def test_missing_file_is_reported(tmp_path: Path) -> None:
    """文件不存在：给"读不到 + 怎么办"，不是 FileNotFoundError。"""
    missing = tmp_path / "nope.json"
    with pytest.raises(ProfileError) as excinfo:
        read_modlist(missing)
    assert "读不到要导入的清单文件" in excinfo.value.message
    assert str(missing) in excinfo.value.message


def test_entry_must_be_an_object(tmp_path: Path) -> None:
    """条目不是对象：指出第几条。"""
    bad = write_json(tmp_path / "bad.json", {"schema_version": 1, "mods": ["carpet"]})
    with pytest.raises(ProfileError) as excinfo:
        read_modlist(bad)
    assert "第 1 条记录格式不正确" in excinfo.value.message
    assert "应为 JSON 对象" in excinfo.value.message


def test_entry_without_any_name_is_rejected(tmp_path: Path) -> None:
    """条目认不出是谁：拒绝（否则所有空条目会挤成同一条）。"""
    bad = write_json(tmp_path / "bad.json",
                     {"schema_version": 1, "mods": [{"notes": "什么都没有"}]})
    with pytest.raises(ProfileError) as excinfo:
        read_modlist(bad)
    assert "缺少名称" in excinfo.value.message


def test_entry_field_type_is_rejected(tmp_path: Path) -> None:
    """字段类型不对：说清字段名、应为的类型、实际的类型。"""
    bad = write_json(tmp_path / "bad.json", {"schema_version": 1, "mods": [
        {"display_name": "Carpet", "file_name": 26}]})
    with pytest.raises(ProfileError) as excinfo:
        read_modlist(bad)
    message = excinfo.value.message
    assert "「file_name」应为文本" in message and "数字" in message
    assert "第 1 条" in message


def test_entry_sources_type_is_rejected(tmp_path: Path) -> None:
    """sources 不是"文本对照表"时同样要挡住（否则合并时会崩在 dict() 上）。"""
    bad = write_json(tmp_path / "bad.json", {"schema_version": 1, "mods": [
        {"display_name": "Carpet", "sources": ["modrinth"]}]})
    with pytest.raises(ProfileError) as excinfo:
        read_modlist(bad)
    assert "「sources」应为文本对照表" in excinfo.value.message


def test_entry_detected_type_is_rejected(tmp_path: Path) -> None:
    """detected 里的列表也检查（类型不对会在 Detected.from_dict 里崩）。"""
    bad = write_json(tmp_path / "bad.json", {"schema_version": 1, "mods": [
        {"display_name": "Carpet", "detected": {"mc_versions": 5}}]})
    with pytest.raises(ProfileError) as excinfo:
        read_modlist(bad)
    assert "detected.mc_versions" in excinfo.value.message


def test_failed_import_leaves_the_target_profile_untouched(tmp_path: Path) -> None:
    """任何一条错误路径都不许改动用户的清单：要么导入成功，要么什么都没发生。"""
    profiles = tmp_path / "profiles"
    save_profile(make_profile("demo", entry("carpet")), profile_path(profiles, "demo"))
    before = profile_path(profiles, "demo").read_bytes()
    bad = write_json(tmp_path / "bad.json", {"schema_version": 1, "mods": [{"file_name": 3}]})

    with pytest.raises(ProfileError):
        import_modlist(bad, profiles_dir=profiles, profile_name="demo")

    assert profile_path(profiles, "demo").read_bytes() == before


def test_read_modlist_tolerates_bom(tmp_path: Path) -> None:
    """对方用记事本另存过 -> 带 BOM 也要能读（与 load_profile 一致）。"""
    path = tmp_path / "bom.json"
    path.write_text(json.dumps({"schema_version": 1, "name": "B", "mods": [
        {"key": "carpet", "display_name": "Carpet", "sources": {"modrinth": "carpet"}}]},
        ensure_ascii=False), encoding="utf-8-sig")

    profile = read_modlist(path)
    assert profile.name == "B" and profile.mods[0].display_name == "Carpet"


def test_import_accepts_an_arbitrary_file_name(tmp_path: Path) -> None:
    """对方把文件改名了也要能导入（清单名取自文件里的 name，不看文件名）。"""
    source = export_to(tmp_path, make_profile("朋友的服务器", entry("carpet")),
                       name="modlist_随便改的名字.json")
    profile = read_modlist(source)
    assert profile.name == "朋友的服务器"


def test_schema_version_constant_matches_the_profile_model() -> None:
    """导入认的版本号必须与写出清单的模型一致 —— 否则自己导的自己导不回来。"""
    assert MODLIST_SCHEMA_VERSION == Profile().schema_version
