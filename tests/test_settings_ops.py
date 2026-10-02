"""R3-A02：core/settings_ops.py 的纯函数设置操作（离线）。"""
from __future__ import annotations

import pytest

from modcheck.core.models import Loader, Settings
from modcheck.core.settings_ops import (COLORS, TTL_KEYS, clone, is_null_word, mask_secret,
                                        parse_proxy, reset_settings, set_cache_ttl,
                                        set_color, set_concurrency, set_curseforge_key,
                                        set_default_loader, set_default_mc, set_proxy)
from modcheck.errors import ConfigError
from modcheck.storage.settings import load_settings

KNOWN = ["26.3", "26.2", "26.1", "1.21.4"]


def test_clone_is_deep_and_equal() -> None:
    """clone 出来的对象内容相同，但 dict 字段不共享。"""
    original = Settings()
    copy = clone(original)
    assert copy.to_dict() == original.to_dict()
    copy.cache_ttl_hours["mojang"] = 999.0
    copy.providers["curseforge"]["api_key"] = "x"
    assert original.cache_ttl_hours["mojang"] == 24.0
    assert original.providers["curseforge"]["api_key"] is None


def test_setters_never_mutate_original() -> None:
    """每个 setter 都返回新对象，原对象一个字段都不许变。"""
    original = Settings()
    snapshot = original.to_dict()
    set_default_mc(original, "26.3", known=KNOWN)
    set_default_loader(original, "forge")
    set_color(original, "never")
    set_proxy(original, "http://127.0.0.1:7890")
    set_concurrency(original, 2)
    set_cache_ttl(original, "api", 12)
    set_curseforge_key(original, "abcd1234")
    assert original.to_dict() == snapshot


# ---------------------------------------------------------------- 默认游戏版本
def test_default_mc_ok_and_clear() -> None:
    """合法版本号写入；null 系列输入清除。"""
    assert set_default_mc(Settings(), "26.3", known=KNOWN).default_mc_version == "26.3"
    assert set_default_mc(Settings(), "26.3", known=KNOWN).default_mc_version != ""
    for word in ("", "  ", "null", "NONE", "-", "nil"):
        assert set_default_mc(Settings(default_mc_version="26.3"), word,
                              known=KNOWN).default_mc_version is None
    assert set_default_mc(Settings(default_mc_version="26.3"), None,
                          known=KNOWN).default_mc_version is None


def test_default_mc_skips_known_check_when_offline() -> None:
    """known 为空（没联网）时只校验格式，不校验存在性。"""
    assert set_default_mc(Settings(), "99.9", known=()).default_mc_version == "99.9"
    assert set_default_mc(Settings(), "99.9", known=None).default_mc_version == "99.9"


@pytest.mark.parametrize("bad,text", [
    ("26.3x", "无法识别的游戏版本"),
    ("abc", "无法识别的游戏版本"),
    ("26.4-snapshot-2", "是快照版本"),
    ("24w14a", "是快照版本"),
    ("1.20.9", "官方版本列表中不存在"),
])
def test_default_mc_rejects(bad: str, text: str) -> None:
    """非法 / 快照 / 不在官方清单：一律 ConfigError，且给的是对应那句文案。"""
    with pytest.raises(ConfigError) as exc:
        set_default_mc(Settings(), bad, known=KNOWN)
    assert text in str(exc.value)


# ---------------------------------------------------------------- 默认加载器
@pytest.mark.parametrize("raw,expected", [
    ("fabric", Loader.FABRIC), ("FABRIC", Loader.FABRIC),
    ("neoforge", Loader.NEOFORGE), ("forge", Loader.FORGE),
])
def test_default_loader_ok(raw: str, expected: Loader) -> None:
    """三种加载器都认，大小写不敏感。"""
    assert set_default_loader(Settings(), raw).default_loader is expected


def test_default_loader_clear_and_bad() -> None:
    """清除 = 回到默认 Fabric；不认识的加载器报错。"""
    assert set_default_loader(Settings(default_loader=Loader.FORGE),
                              None).default_loader is Loader.FABRIC
    assert set_default_loader(Settings(default_loader=Loader.FORGE),
                              "null").default_loader is Loader.FABRIC
    with pytest.raises(ConfigError):
        set_default_loader(Settings(), "quilt")


# ---------------------------------------------------------------- 颜色
@pytest.mark.parametrize("value", COLORS)
def test_color_ok(value: str) -> None:
    """三种颜色模式都接受。"""
    assert set_color(Settings(), value).color == value


def test_color_bad() -> None:
    """其它值一律拒绝，并给出逐字文案。"""
    with pytest.raises(ConfigError) as exc:
        set_color(Settings(), "rainbow")
    assert "✗ 颜色只能为 auto / always / never（当前输入为 rainbow）。未做改动。" in str(exc.value)


# ---------------------------------------------------------------- 代理（D42）
@pytest.mark.parametrize("raw", ["", "   ", "null", "NULL", "none", "-", "nil"])
def test_proxy_clear_words(raw: str) -> None:
    """D42：null/none/-/空串一律表示清除。"""
    assert parse_proxy(raw) is None
    assert set_proxy(Settings(proxy="http://a:1"), raw).proxy is None


@pytest.mark.parametrize("raw,expected", [
    ("http://127.0.0.1:7890", "http://127.0.0.1:7890"),
    ("  socks5://127.0.0.1:1080  ", "socks5://127.0.0.1:1080"),
    ("https://proxy.example.com", "https://proxy.example.com"),
])
def test_proxy_ok(raw: str, expected: str) -> None:
    """合法代理地址原样保存（去掉首尾空格）。"""
    assert parse_proxy(raw) == expected
    assert set_proxy(Settings(), raw).proxy == expected


@pytest.mark.parametrize("raw", ["127.0.0.1:7890", "http://", "http:///x", "://host", "just a string"])
def test_proxy_bad(raw: str) -> None:
    """不满足 scheme://host 的一律拒绝（绝不落盘）。"""
    with pytest.raises(ConfigError):
        set_proxy(Settings(), raw)


def test_is_null_word() -> None:
    """清除语义判定。"""
    assert is_null_word(None) and is_null_word(" Null ") and not is_null_word("http://x:1")


# ---------------------------------------------------------------- 并发数
@pytest.mark.parametrize("value", [1, 8, "3"])
def test_concurrency_ok(value) -> None:
    """1 / 8 边界以及数字字符串都通过。"""
    assert set_concurrency(Settings(), value).concurrency == int(value)


@pytest.mark.parametrize("value", [0, 9, -1, 100, "x", "", None])
def test_concurrency_bad(value) -> None:
    """越界与非法输入报错，并给逐字文案。"""
    with pytest.raises(ConfigError) as exc:
        set_concurrency(Settings(), value)
    assert "并发数需在 1 到 8 之间" in str(exc.value)


# ---------------------------------------------------------------- 缓存有效期
@pytest.mark.parametrize("hours", [1, 168, 6.5, "12"])
def test_cache_ttl_ok(hours) -> None:
    """1 / 168 边界通过，且只改指定的那一项。"""
    result = set_cache_ttl(Settings(), "api", hours)
    assert result.cache_ttl_hours["api"] == float(hours)
    assert result.cache_ttl_hours["mojang"] == 24.0


@pytest.mark.parametrize("hours", [0, 169, -5, "x", None])
def test_cache_ttl_bad(hours) -> None:
    """越界与非法输入报错。"""
    with pytest.raises(ConfigError) as exc:
        set_cache_ttl(Settings(), "api", hours)
    assert "缓存有效期需在 1 到 168 小时之间" in str(exc.value)


def test_cache_ttl_unknown_key() -> None:
    """不认识的缓存键直接拒绝。"""
    with pytest.raises(ConfigError) as exc:
        set_cache_ttl(Settings(), "modrinth", 6)
    assert "未知的设置项" in str(exc.value)
    assert TTL_KEYS == ("mojang", "api")


# ---------------------------------------------------------------- CurseForge Key
def test_curseforge_key_set_and_clear() -> None:
    """设置 / 清除 API Key，并保持 providers 里其它字段。"""
    settings = set_curseforge_key(Settings(), "abcd1234")
    assert settings.providers["curseforge"]["api_key"] == "abcd1234"
    assert settings.providers["curseforge"]["enabled"] is False
    assert set_curseforge_key(settings, "null").providers["curseforge"]["api_key"] is None
    assert set_curseforge_key(settings, None).providers["curseforge"]["api_key"] is None


@pytest.mark.parametrize("value,expected", [
    ("abcd1234", "****1234"),
    ("1234", "****1234"),
    ("ab", "****ab"),
    ("", ""),
    (None, ""),
])
def test_mask_secret(value, expected: str) -> None:
    """回显只显示后 4 位。"""
    assert mask_secret(value) == expected


# ---------------------------------------------------------------- 重置
def test_reset_matches_load_defaults(tmp_path) -> None:
    """reset_settings() 必须等于「配置文件不存在时」的默认值。"""
    defaults = load_settings(tmp_path / "not-exists.json")
    assert reset_settings().to_dict() == defaults.to_dict()


def test_reset_is_independent() -> None:
    """两次 reset 互不影响。"""
    first = reset_settings()
    first.concurrency = 1
    assert reset_settings().concurrency == 6
