"""T-15 存储层测试：目录探测、设置读写、清单读写与合并。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modcheck.core.models import Loader, MatchStatus, ModEntry, Profile, SourceKind
from modcheck.errors import ConfigError, ProfileError
from modcheck.storage import paths as p
from modcheck.storage.profiles import (copy_profile, dedupe_by_key, key_of, list_profiles,
                                       load_profile, merge_entries, new_profile,
                                       profile_path, rename_profile, save_profile,
                                       validate_profile_name)
from modcheck.storage.settings import SETTING_KEYS, load_settings, save_settings, set_setting


# ---------------------------------------------------------------- paths
def test_resolve_config_dir_priority(tmp_path: Path) -> None:
    """--config-dir > 环境变量 > 回退目录。"""
    env_dir = tmp_path / "from-env"
    assert p.resolve_config_dir(str(tmp_path / "cli"), env={}) == tmp_path / "cli"
    assert p.resolve_config_dir(None, env={p.ENV_CONFIG_DIR: str(env_dir)}) == env_dir
    assert p.resolve_config_dir(None, env={}) == p.fallback_config_dir()


def test_portable_dir_is_used_when_writable(tmp_path: Path) -> None:
    """打包模式下（给了 exe 目录）优先用便携目录。"""
    exe_dir = tmp_path / "app"
    exe_dir.mkdir()
    resolved = p.resolve_config_dir(None, env={}, exe_dir=exe_dir)
    assert resolved == exe_dir / p.PORTABLE_DIRNAME


def test_is_writable_and_fallback(tmp_path: Path) -> None:
    """可写判断与回退。"""
    target = tmp_path / "cfg"
    assert p.is_writable(target) is True
    final, fell_back = p.ensure_config_dir(target)
    assert final == target
    assert fell_back is False


def test_path_helpers(tmp_path: Path) -> None:
    """各路径拼接。"""
    assert p.settings_path(tmp_path) == tmp_path / "settings.json"
    assert p.profiles_dir(tmp_path) == tmp_path / "profiles"
    assert p.http_cache_dir(tmp_path) == tmp_path / "cache" / "http"


# ---------------------------------------------------------------- settings
def test_settings_round_trip_and_defaults(tmp_path: Path) -> None:
    """设置读写往返；缺失时返回默认值（不写盘）。"""
    path = tmp_path / "settings.json"
    settings = load_settings(path)
    assert settings.default_loader is Loader.FABRIC
    assert not path.exists()
    settings.default_mc_version = "26.3"
    save_settings(path, settings)
    assert load_settings(path).default_mc_version == "26.3"
    assert "\ufeff" not in path.read_text(encoding="utf-8")


def test_settings_corrupt_is_backed_up(tmp_path: Path) -> None:
    """损坏的设置备份后重建默认值，绝不崩。"""
    path = tmp_path / "settings.json"
    path.write_text("{ not json", encoding="utf-8")
    settings = load_settings(path)
    assert settings.default_loader is Loader.FABRIC
    backups = list(tmp_path.glob("settings.json.bak-*"))
    assert len(backups) == 1


def test_set_setting_validates() -> None:
    """set_setting 的范围与枚举校验。"""
    settings = load_settings(Path("nope") / "settings.json")
    assert set_setting(settings, "default_loader", "neoforge").default_loader is Loader.NEOFORGE
    assert set_setting(settings, "concurrency", "3").concurrency == 3
    assert set_setting(settings, "proxy", "http://127.0.0.1:7890").proxy == "http://127.0.0.1:7890"
    assert set_setting(settings, "providers.curseforge.api_key", "K").providers["curseforge"]["api_key"] == "K"
    with pytest.raises(ConfigError):
        set_setting(settings, "no.such.key", "1")
    with pytest.raises(ConfigError):
        set_setting(settings, "concurrency", "100")
    with pytest.raises(ConfigError):
        set_setting(settings, "concurrency", "abc")
    with pytest.raises(ConfigError):
        set_setting(settings, "default_loader", "quilt")
    assert "default_mc_version" in SETTING_KEYS


# ---------------------------------------------------------------- profiles
def _entry(key: str, **kw: object) -> ModEntry:
    return ModEntry(key=key, display_name=str(kw.pop("display_name", key)), **kw)  # type: ignore[arg-type]


def test_profile_name_validation() -> None:
    """清单名校验：空名与非法字符。"""
    validate_profile_name("服务器A")
    for bad in ("", "a/b", "a\\b", "a:b", "a*b", "a?b", 'a"b', "a<b", "a>b", "a|b"):
        with pytest.raises(ConfigError):
            validate_profile_name(bad)


def test_profile_save_load_round_trip(tmp_path: Path) -> None:
    """清单原子写 + 往返一致（含中文）。"""
    profile = new_profile("服务器A", "测试")
    profile.mods.append(_entry("carpet", display_name="Carpet", cn_name="地毯"))
    path = profile_path(tmp_path, "服务器A")
    save_profile(profile, path)
    loaded = load_profile(path)
    assert loaded.name == "服务器A"
    assert loaded.mods[0].cn_name == "地毯"
    assert [p.name for p in tmp_path.iterdir()] == ["服务器A.json"]


def test_load_corrupt_profile_raises_e11(tmp_path: Path) -> None:
    """损坏 JSON -> ProfileError，文案对齐 PRD E11。"""
    path = tmp_path / "bad.json"
    path.write_text('{"mods": [', encoding="utf-8")
    with pytest.raises(ProfileError) as exc:
        load_profile(path)
    assert "清单文件无法读取" in str(exc.value)
    assert "不是合法的 JSON" in str(exc.value) or "Expecting" in str(exc.value)


def test_load_profile_without_mods_raises_e12(tmp_path: Path) -> None:
    """缺少 mods 字段 -> E12 文案。"""
    path = tmp_path / "weird.json"
    path.write_text(json.dumps({"name": "x"}), encoding="utf-8")
    with pytest.raises(ProfileError) as exc:
        load_profile(path)
    assert "未找到「mods」字段" in str(exc.value)


def test_list_profiles_skips_broken(tmp_path: Path) -> None:
    """一个坏清单不影响其它清单。"""
    save_profile(new_profile("ok1"), profile_path(tmp_path, "ok1"))
    (tmp_path / "broken.json").write_text("{oops", encoding="utf-8")
    summaries = list_profiles(tmp_path)
    assert [s.name for s in summaries] == ["broken", "ok1"]
    assert summaries[0].error != ""


def test_key_of_three_levels() -> None:
    """key 三级降级。"""
    assert key_of(_entry("x", mod_id="Carpet")) == "carpet"
    assert key_of(_entry("x", sha1="AB" * 20)) == "sha1:" + "ab" * 20
    assert key_of(_entry("x", display_name="Ferrite Core")) == "ferritecore"


def test_merge_entries_is_idempotent(tmp_path: Path) -> None:
    """合并幂等：合并两次结果相同。"""
    existing = [_entry("carpet", mod_id="carpet", file_name="a.jar", cn_name="地毯")]
    incoming = [_entry("carpet", mod_id="carpet", file_name="b.jar",
                       sources={"modrinth": "carpet"})]
    once, stats = merge_entries(existing, incoming)
    twice, _ = merge_entries(once, incoming)
    assert [m.to_dict() for m in once] == [m.to_dict() for m in twice]
    assert stats.merged == 1
    assert once[0].sources["modrinth"] == "carpet"
    assert once[0].cn_name == "地毯"
    assert "b.jar" in once[0].aliases


def test_merge_warns_on_multiple_files() -> None:
    """同一 modid 多文件必须告警（服务器启动失败的真实事故）。"""
    existing = [_entry("carpet", mod_id="carpet", file_name="a.jar")]
    incoming = [_entry("carpet", mod_id="carpet", file_name="b.jar")]
    _, stats = merge_entries(existing, incoming)
    assert any("多个版本文件" in w for w in stats.warnings)


def test_dedupe_by_key_reports_duplicates() -> None:
    """清单内部重复 key -> 合并并警告（PRD E24）。"""
    mods = [_entry("a", mod_id="carpet", display_name="Carpet", cn_name="地毯"),
            _entry("b", mod_id="carpet", display_name="Carpet Mod")]
    merged, warnings = dedupe_by_key(mods)
    assert len(merged) == 1
    assert merged[0].cn_name == "地毯"
    assert any("modid" in w for w in warnings)


def test_copy_and_rename_profile(tmp_path: Path) -> None:
    """复制与重命名。"""
    source = profile_path(tmp_path, "A")
    save_profile(new_profile("A"), source)
    copy_profile(source, profile_path(tmp_path, "B"))
    assert load_profile(profile_path(tmp_path, "B")).name == "B"
    rename_profile(profile_path(tmp_path, "A"), profile_path(tmp_path, "C"))
    assert not source.exists()
    assert load_profile(profile_path(tmp_path, "C")).name == "C"
    with pytest.raises(ProfileError):
        rename_profile(profile_path(tmp_path, "C"), profile_path(tmp_path, "B"))


def test_profile_round_trip_via_dict() -> None:
    """序列化包含 match_status / source_kind 等枚举。"""
    profile = Profile(name="x", mods=[_entry("k", mod_id="m", match_status=MatchStatus.GUESS,
                                             source_kind=SourceKind.FILENAME)])
    restored = Profile.from_dict(profile.to_dict())
    assert restored.mods[0].match_status is MatchStatus.GUESS
    assert restored.mods[0].source_kind is SourceKind.FILENAME
