"""T-04 数据模型测试：往返序列化、枚举解析、候选顺序。"""
from __future__ import annotations

import json

import pytest

from modcheck.core.models import (Detected, Loader, MatchStatus, ModEntry, Profile,
                                  ReasonCode, Settings, SourceKind, Status, VersionInfo)
from modcheck.errors import ConfigError


def test_loader_parse_and_display() -> None:
    """加载器解析大小写不敏感，非法值抛 ConfigError。"""
    assert Loader.parse("FABRIC") is Loader.FABRIC
    assert Loader.parse(" NeoForge ") is Loader.NEOFORGE
    assert Loader.FABRIC.display_name == "Fabric"
    assert Loader.NEOFORGE.display_name == "NeoForge"
    with pytest.raises(ConfigError) as exc:
        Loader.parse("quilt")
    assert "quilt" in str(exc.value)


def test_enum_values_match_brief() -> None:
    """状态与原因码取值必须与基线 §7 表格逐字一致。"""
    assert [s.value for s in Status] == ["ready", "degraded", "blocked", "unknown", "ignored"]
    assert ReasonCode.NO_FILES.value == "NO_FILES"
    assert ReasonCode.MC_VERSION_FUZZY.value == "MC_VERSION_FUZZY"
    assert {m.value for m in MatchStatus} == {"exact", "manual", "unmatched", "ignored", "guess"}
    assert SourceKind.HASH.display == "文件指纹"
    assert SourceKind.FILENAME.display == "文件名猜测"


def _sample_profile() -> Profile:
    return Profile(
        name="服务器A", description="测试用", created_at="2026-10-01T12:00:00+08:00",
        updated_at="2026-10-01T12:00:00+08:00",
        mods=[
            ModEntry(
                key="carpet", display_name="Carpet", cn_name="地毯", mod_id="carpet",
                file_name="[地毯] fabric-carpet-26.1+v260402.jar", sha1="a" * 40,
                aliases=["fabric-carpet-26.1+v260402.jar"],
                sources={"modrinth": "carpet", "curseforge": None},
                detected=Detected(mc_versions=["26.1"], loaders=["fabric"], mod_version="v260402"),
                match_status=MatchStatus.EXACT, source_kind=SourceKind.HASH,
                current_version="26.1", notes="备注", added_at="x", updated_at="y",
            ),
            ModEntry(key="unknown", display_name="未知模组"),
        ])


def test_profile_json_round_trip() -> None:
    """Profile 经 JSON（ensure_ascii=False）往返后必须完全一致。"""
    profile = _sample_profile()
    text = json.dumps(profile.to_dict(), ensure_ascii=False, indent=2)
    assert "地毯" in text
    restored = Profile.from_dict(json.loads(text))
    assert restored.to_dict() == profile.to_dict()
    assert restored.mods[0].cn_name == "地毯"
    assert restored.mods[0].sources["curseforge"] is None
    assert restored.mods[1].match_status is MatchStatus.UNMATCHED


def test_profile_unknown_fields_ignored() -> None:
    """未知字段读取时忽略，不报错。"""
    raw = {"schema_version": 1, "name": "x", "mods": [], "future_field": {"a": 1}}
    profile = Profile.from_dict(raw)
    assert profile.name == "x"
    assert profile.mods == []


def test_profile_missing_mods_raises() -> None:
    """缺少 mods 字段 -> ConfigError（PRD E12）。"""
    with pytest.raises(ConfigError) as exc:
        Profile.from_dict({"name": "x"})
    assert "mods" in str(exc.value)


def test_version_info_api_and_cache_round_trip() -> None:
    """VersionInfo 从 API 构造、缓存瘦身、还原。"""
    raw = {
        "id": "V1", "project_id": "P1", "version_number": "26.3", "name": "26.3",
        "date_published": "2026-09-18T10:00:00Z", "version_type": "release",
        "game_versions": ["26.3"], "loaders": ["fabric"],
        "files": [{"filename": "fabric-carpet-26.3+v260915.jar", "url": "u", "primary": True,
                   "size": 100, "hashes": {"sha1": "aa", "sha512": "bb"}}],
    }
    version = VersionInfo.from_api(raw)
    assert version.is_release is True
    assert version.primary_file is not None
    assert version.primary_file.filename == "fabric-carpet-26.3+v260915.jar"
    cached = version.to_cache()
    assert "sha512" not in cached["files"][0]["hashes"]
    assert VersionInfo.from_cache(cached).version_number == "26.3"
    assert VersionInfo.from_cache(cached).game_versions == ("26.3",)


def test_version_info_primary_file_falls_back_to_first() -> None:
    """没有 primary 标记时取第一个文件。"""
    version = VersionInfo.from_api({"id": "V", "files": [
        {"filename": "a.jar", "primary": False, "size": 1, "hashes": {}, "url": ""},
        {"filename": "b.jar", "primary": False, "size": 1, "hashes": {}, "url": ""},
    ]})
    assert version.primary_file is not None
    assert version.primary_file.filename == "a.jar"


def test_search_candidates_order() -> None:
    """候选名顺序：mod_id -> 展示名 -> 文件名候选 -> key，且去重。"""
    entry = ModEntry(key="carpet", display_name="Carpet Mod", mod_id="carpet",
                     file_name="[地毯] fabric-carpet-26.1+v260402.jar")
    candidates = entry.search_candidates()
    assert candidates[0] == "carpet"
    assert candidates[1] == "Carpet Mod"
    assert "地毯" not in candidates


def test_settings_round_trip_and_defaults() -> None:
    """Settings 往返一致；坏值退化为默认值而不抛异常。"""
    settings = Settings(default_mc_version="26.3", proxy="http://127.0.0.1:7890", concurrency=8)
    restored = Settings.from_dict(json.loads(json.dumps(settings.to_dict())))
    assert restored.default_mc_version == "26.3"
    assert restored.default_loader is Loader.FABRIC
    assert restored.cache_ttl_hours == {"mojang": 24.0, "api": 6.0}
    broken = Settings.from_dict({"default_loader": "quilt", "concurrency": "abc",
                                 "color": "rainbow", "cache_ttl_hours": {"api": "x"}})
    assert broken.default_loader is Loader.FABRIC
    assert broken.concurrency == 6
    assert broken.color == "auto"
    assert broken.cache_ttl_hours["api"] == 6.0
    assert broken.providers["curseforge"]["enabled"] is False


def test_best_name_priority() -> None:
    """best_name：中文名 > 展示名 > modid > key。"""
    assert ModEntry(key="k", display_name="D", cn_name="中", mod_id="m").best_name == "中"
    assert ModEntry(key="k", display_name="D", mod_id="m").best_name == "D"
    assert ModEntry(key="k", display_name="", mod_id="m").best_name == "m"
    assert ModEntry(key="k", display_name="").best_name == "k"
