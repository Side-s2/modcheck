"""R3-A01：core/profile_ops.py 的纯函数操作（离线）。"""
from __future__ import annotations

import pytest

from modcheck.core.models import MatchStatus, ModEntry, Profile
from modcheck.core.profile_ops import (OpResult, add_mod, clone_entry, entry_identifiers,
                                       now_iso, page_of, parse_project_selector, remove_mods,
                                       rename, resolve_selector, set_ignored, set_source,
                                       validate_profile_name)
from modcheck.errors import ConfigError
from modcheck.storage.profiles import now_iso as storage_now_iso

OLD = "2000-01-01T00:00:00+08:00"


def entry(key: str, *, name: str = "", mod_id: str | None = None, slug: str | None = None,
          cn: str | None = None, file_name: str | None = None,
          aliases: list[str] | None = None, status: MatchStatus = MatchStatus.EXACT) -> ModEntry:
    """造一条清单记录。"""
    item = ModEntry(key=key, display_name=name or key, mod_id=mod_id, cn_name=cn,
                    file_name=file_name, aliases=list(aliases or []),
                    match_status=status, updated_at=OLD)
    if slug:
        item.sources = {"modrinth": slug}
    return item


def profile(*mods: ModEntry, name: str = "服务器A") -> Profile:
    """造一份清单（updated_at 故意设成很旧的值，便于断言"被刷新过"）。"""
    return Profile(name=name, created_at=OLD, updated_at=OLD, mods=list(mods))


def sample() -> Profile:
    """三条典型记录：carpet（中文名+文件名）/ sodium / lithium（无平台标识）。"""
    return profile(
        entry("carpet", name="Carpet", mod_id="carpet", slug="carpet", cn="地毯",
              file_name="fabric-carpet-26.1+v260402.jar"),
        entry("sodium", name="Sodium", mod_id="sodium", slug="sodium", cn="钠"),
        entry("lithium", name="Lithium", mod_id="lithium",
              status=MatchStatus.UNMATCHED),
    )


# ---------------------------------------------------------------- 定位 (D33)
@pytest.mark.parametrize("selector", [
    "carpet",              # key
    "CARPET",              # key（大小写不敏感）
    " carpet ",            # 前后空格
    "地毯",                 # cn_name
    "Carpet",              # display_name
    "fabric-carpet-26.1+v260402.jar",   # file_name
    "1",                   # 编号
])
def test_resolve_hits_every_identifier(selector: str) -> None:
    """D33：key / modid / slug / 名称 / 中文名 / 文件名 / 编号 都能命中。"""
    result = resolve_selector(sample(), selector)
    assert result.reason_key == "found"
    assert result.entry is not None and result.entry.key == "carpet"


def test_resolve_slug_first_then_cn() -> None:
    """slug 优先于中文名（两者指向同一条时也是唯一命中）。"""
    result = resolve_selector(sample(), "sodium")
    assert result.entry is not None and result.entry.cn_name == "钠"


def test_resolve_ambiguous() -> None:
    """同一个名字对应两条记录 -> ambiguous 并给出全部候选。"""
    prof = profile(entry("a", name="同名", mod_id="a"), entry("b", name="同名", mod_id="b"))
    result = resolve_selector(prof, "同名")
    assert result.entry is None
    assert result.reason_key == "ambiguous"
    assert [item.key for item in result.candidates] == ["a", "b"]


def test_resolve_not_found_with_suggests() -> None:
    """未命中时给模糊候选建议。"""
    result = resolve_selector(sample(), "sodi")
    assert result.entry is None
    assert result.reason_key == "not_found"
    assert [item.key for item in result.candidates] == ["sodium"]


def test_resolve_not_found_no_suggest() -> None:
    """完全没有相近的条目时候选为空。"""
    result = resolve_selector(sample(), "zzz")
    assert result.entry is None and result.candidates == ()


def test_resolve_empty_selector() -> None:
    """空串直接未命中（不抛异常）。"""
    assert resolve_selector(sample(), "   ").reason_key == "not_found"


def test_identifier_order_matches_d33() -> None:
    """标识顺序必须是 key -> modid -> slug -> display_name -> cn_name -> 文件名。"""
    item = entry("slug:modrinth:carpet", name="Carpet Mod", mod_id="carpet",
                 slug="carpet", cn="地毯", file_name="carpet.jar", aliases=["fabric-carpet"])
    assert entry_identifiers(item) == ["slug:modrinth:carpet", "carpet", "Carpet Mod",
                                       "地毯", "carpet.jar", "fabric-carpet"]


# ---------------------------------------------------------------- 删除
def test_remove_two_mods() -> None:
    """按编号删两条：新清单少两条，原清单不动，updated_at 刷新。"""
    prof = sample()
    result = remove_mods(prof, ["1", "sodium"])
    assert isinstance(result, OpResult) and result.changed is True
    assert [item.key for item in result.profile.mods] == ["lithium"]
    assert len(prof.mods) == 3                      # 原对象绝不被修改
    assert prof.updated_at == OLD
    assert result.profile.updated_at != OLD
    assert result.profile.name == "服务器A"
    assert result.message_key == "manage.remove.done"
    assert result.message_args["count"] == "2" and result.message_args["left"] == "1"


def test_remove_keeps_unmatched_selectors() -> None:
    """部分定位失败时，成功的照删，失败的进 warnings。"""
    result = remove_mods(sample(), ["lithium", "zzz"])
    assert result.changed is True
    assert [item.key for item in result.profile.mods] == ["carpet", "sodium"]
    assert result.warnings == ("zzz",)


def test_remove_nothing_changed() -> None:
    """一个都没命中：changed=False 且返回原对象（调用方据此不写盘）。"""
    prof = sample()
    result = remove_mods(prof, ["zzz"])
    assert result.changed is False and result.profile is prof
    assert result.message_key == "manage.remove.none"


def test_remove_dedupes_same_selector() -> None:
    """同一个模组的两种写法只删一次。"""
    result = remove_mods(sample(), ["carpet", "1", "carpet"])
    assert [item.key for item in result.profile.mods] == ["sodium", "lithium"]


# ---------------------------------------------------------------- 指定平台项目
def test_set_source_writes_slug_and_manual() -> None:
    """指定平台项目：写 sources + match_status=manual + key 变 slug 键。"""
    prof = sample()
    result = set_source(prof, "lithium", provider="modrinth", slug="lithium",
                        title="Lithium")
    assert result.changed is True
    target = next(item for item in result.profile.mods if item.display_name == "Lithium")
    assert target.sources["modrinth"] == "lithium"
    assert target.match_status is MatchStatus.MANUAL
    assert target.key == "slug:modrinth:lithium"
    assert target.updated_at != OLD
    # 原对象没被改（clone 生效）
    original = next(item for item in prof.mods if item.display_name == "Lithium")
    assert original.sources == {} and original.match_status is MatchStatus.UNMATCHED


def test_set_source_missing_entry() -> None:
    """定位不到：changed=False，文案是 entry_missing。"""
    prof = sample()
    result = set_source(prof, "zzz", provider="modrinth", slug="zzz")
    assert result.changed is False and result.profile is prof
    assert result.message_key == "manage.source.entry_missing"


# ---------------------------------------------------------------- 忽略切换
def test_ignore_toggle_and_idempotence() -> None:
    """忽略 -> 已忽略组；重复忽略幂等；取消忽略恢复正常判定。"""
    prof = sample()
    first = set_ignored(prof, "lithium", True)
    assert first.changed is True and first.message_key == "manage.ignore.done"
    ignored = next(item for item in first.profile.mods if item.key == "lithium")
    assert ignored.match_status is MatchStatus.IGNORED

    again = set_ignored(first.profile, "lithium", True)
    assert again.changed is False and again.profile is first.profile
    assert again.message_key == "manage.ignore.done"

    back = set_ignored(first.profile, "lithium", False)
    assert back.changed is True and back.message_key == "manage.ignore.undone"
    restored = next(item for item in back.profile.mods if item.key == "lithium")
    # lithium 没有平台标识 -> 回到 UNMATCHED；有标识的回到 MANUAL
    assert restored.match_status is MatchStatus.UNMATCHED
    sodium_back = set_ignored(set_ignored(sample(), "sodium", True).profile, "sodium", False)
    assert next(item for item in sodium_back.profile.mods
                if item.key == "sodium").match_status is MatchStatus.MANUAL


def test_ignore_missing_entry() -> None:
    """定位不到：changed=False 且不改任何东西。"""
    prof = sample()
    result = set_ignored(prof, "zzz", True)
    assert result.changed is False and result.profile is prof
    assert result.message_key == "manage.ignore.entry_missing"


# ---------------------------------------------------------------- 新增 / 重命名
def test_add_mod_variants() -> None:
    """新增：有 slug 走 slug 键；只有 modid 走 modid 键；都没有走规范化名称。"""
    prof = sample()
    by_slug = add_mod(prof, display_name="New Mod", source_slug="New-Mod")
    assert by_slug.changed is True
    assert by_slug.profile.mods[-1].key == "slug:modrinth:new-mod"
    assert by_slug.profile.mods[-1].match_status is MatchStatus.MANUAL

    by_modid = add_mod(prof, display_name="Other", mod_id="OtherID")
    assert by_modid.profile.mods[-1].key == "otherid"

    by_name = add_mod(prof, display_name="Ferrite Core")
    assert by_name.profile.mods[-1].key == "ferritecore"


def test_add_mod_rejects_empty_and_duplicate() -> None:
    """空名与重名各自给文案，且不产生新记录。"""
    prof = sample()
    empty = add_mod(prof, display_name="   ")
    assert empty.changed is False and empty.message_key == "manage.add.empty"
    dupe = add_mod(prof, display_name="Sodium", mod_id="sodium")
    assert dupe.changed is False and dupe.message_key == "manage.add.exists"
    assert len(dupe.profile.mods) == 3


def test_rename_updates_name_only() -> None:
    """重命名：新对象 name 变了，模组与 created_at 不变，updated_at 刷新。"""
    prof = sample()
    result = rename(prof, " 主服 ")
    assert result.changed is True and result.profile.name == "主服"
    assert prof.name == "服务器A"
    assert len(result.profile.mods) == 3
    assert result.profile.created_at == OLD and result.profile.updated_at != OLD
    assert result.message_args == {"old": "服务器A", "new": "主服"}


def test_rename_same_name_is_noop() -> None:
    """改成同一个名字：changed=False。"""
    prof = sample()
    assert rename(prof, "服务器A").changed is False


@pytest.mark.parametrize("bad", ["", "   ", "a/b", "a:b", "a*b", "a?b", 'a"b', "a<b", "a>b",
                                 "a|b", "a" + chr(92) + "b"])
def test_rename_rejects_invalid_names(bad: str) -> None:
    """非法清单名一律 ConfigError（与 storage 同一句文案）。"""
    with pytest.raises(ConfigError):
        validate_profile_name(bad)
    with pytest.raises(ConfigError):
        rename(sample(), bad)


# ---------------------------------------------------------------- 分页
def test_page_of_two_pages() -> None:
    """30 条 -> 2 页；第 1 页 20 条、第 2 页 10 条。"""
    prof = profile(*[entry("m" + str(i), mod_id="m" + str(i)) for i in range(30)])
    first, pages = page_of(prof, 1)
    assert pages == 2 and len(first) == 20 and first[0].key == "m0"
    second, _ = page_of(prof, 2)
    assert len(second) == 10 and second[0].key == "m20"


def test_page_of_boundaries() -> None:
    """第 0 页 / 越界页被夹到合法范围；空清单也算 1 页。"""
    prof = profile(*[entry("m" + str(i), mod_id="m" + str(i)) for i in range(30)])
    assert [item.key for item in page_of(prof, 0)[0]] == [item.key for item in page_of(prof, 1)[0]]
    assert page_of(prof, 99)[0][-1].key == "m29"
    assert page_of(profile(), 1) == ([], 1)
    assert page_of(profile(), 7) == ([], 1)


def test_page_of_custom_size() -> None:
    """size 可调，且最小 1。"""
    prof = profile(*[entry("m" + str(i), mod_id="m" + str(i)) for i in range(5)])
    assert page_of(prof, 2, size=2)[0][0].key == "m2"
    assert page_of(prof, 1, size=0) == ([prof.mods[0]], 5)


# ---------------------------------------------------------------- URL 解析
@pytest.mark.parametrize("raw,expected", [
    ("carpet", "carpet"),
    ("  Carpet  ", "carpet"),
    ("carpet-tis-addition", "carpet-tis-addition"),
    ("carpet_2.x", "carpet_2.x"),
    ("https://modrinth.com/mod/carpet", "carpet"),
    ("https://modrinth.com/mod/carpet/", "carpet"),
    ("https://modrinth.com/mod/carpet?foo=bar", "carpet"),
    ("https://modrinth.com/mod/carpet/versions", "carpet"),
    ("https://www.modrinth.com/mod/fabric-api", "fabric-api"),
    ("https://modrinth.com/project/jei", "jei"),
    ("http://modrinth.com/mod/sodium#top", "sodium"),
])
def test_parse_project_selector_ok(raw: str, expected: str) -> None:
    """slug 与各种链接写法都要能解析。"""
    assert parse_project_selector(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "   ", "https://example.com/mod/carpet", "https://modrinth.com/",
    "https://modrinth.com/mod/", "ftp://modrinth.com/mod/carpet", "carpet xyz",
    "!!!", "a" * 65, "https://modrinth.com/user/carpet", "/mod/carpet",
])
def test_parse_project_selector_bad(raw: str) -> None:
    """非法串返回 None（绝不猜）。"""
    assert parse_project_selector(raw) is None


# ---------------------------------------------------------------- 其它
def test_clone_entry_is_deep() -> None:
    """clone_entry 必须深拷贝（改副本不影响原件）。"""
    original = entry("carpet", name="Carpet", slug="carpet", aliases=["a"])
    copy = clone_entry(original)
    copy.sources["modrinth"] = "other"
    copy.aliases.append("b")
    copy.display_name = "changed"
    assert original.sources["modrinth"] == "carpet"
    assert original.aliases == ["a"] and original.display_name == "Carpet"


def test_now_iso_matches_storage_format() -> None:
    """core 的时间戳格式必须与 storage 一致（否则清单里会出现两种格式）。"""
    assert len(now_iso()) == len(storage_now_iso())
    assert now_iso()[:4].isdigit() and now_iso()[4] == "-"
