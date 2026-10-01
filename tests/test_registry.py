"""T-13 注册表 / CurseForge 占位测试。"""
from __future__ import annotations

import pytest

from fakes import FakeClock, FakeTransport
from modcheck.core.models import Loader, Settings
from modcheck.errors import ProviderUnavailable
from modcheck.providers.curseforge import CurseForgeProvider
from modcheck.providers.http import HttpConfig, HttpClient, RateLimiter
from modcheck.providers.modrinth import ModrinthProvider
from modcheck.providers.registry import ProviderRegistry


def make_client(handler) -> tuple[HttpClient, FakeTransport]:
    """最小可注入客户端。"""
    clock = FakeClock()
    transport = FakeTransport(handler)
    cfg = HttpConfig(rate_limit_per_min=100000)
    client = HttpClient(cfg, limiter=RateLimiter(cfg.rate_limit_per_min, clock=clock.clock,
                                                 sleep=clock.sleep),
                        clock=clock.clock, sleep=clock.sleep, transport=transport)
    return client, transport


def test_default_registry_has_modrinth_only() -> None:
    """默认设置：只有 Modrinth 可用，CurseForge 存在但未启用。"""
    client, _ = make_client(lambda *a: None)
    registry = ProviderRegistry.from_settings(Settings(), client)
    names = [p.name for p in registry.enabled()]
    assert names == ["modrinth"]
    assert registry.by_name("curseforge") is not None
    assert registry.by_name("curseforge").available is False  # type: ignore[union-attr]
    assert registry.primary().name == "modrinth"


def test_registry_without_enabled_provider_raises() -> None:
    """一个可用数据源都没有 -> ProviderUnavailable（退出码 4）。"""
    registry = ProviderRegistry(providers=[CurseForgeProvider(None)])
    with pytest.raises(ProviderUnavailable) as exc:
        registry.primary()
    assert exc.value.exit_code == 4


def test_curseforge_placeholder_raises_and_never_calls_network() -> None:
    """CF 占位：所有方法抛 ProviderUnavailable，且零网络调用。"""
    client, transport = make_client(lambda *a: None)
    provider = CurseForgeProvider(None)
    assert provider.available is False
    with pytest.raises(ProviderUnavailable):
        provider.search("create")
    with pytest.raises(ProviderUnavailable):
        provider.get_project("create")
    with pytest.raises(ProviderUnavailable):
        provider.get_versions("create")
    with pytest.raises(ProviderUnavailable):
        provider.releases_for_loader("create", Loader.FABRIC)
    with pytest.raises(ProviderUnavailable):
        provider.compat_releases("create", "26.3", Loader.FABRIC)
    with pytest.raises(ProviderUnavailable):
        provider.any_for_loader("create", Loader.FABRIC)
    with pytest.raises(ProviderUnavailable):
        provider.resolve_by_hash(["a" * 40])
    assert transport.count == 0
    assert client.stats == (0, 0)


def test_enabling_curseforge_still_unavailable_this_round() -> None:
    """即使设置里启用了 CF，本期它仍然不可用（还没实现）。"""
    settings = Settings()
    settings.providers["curseforge"] = {"enabled": True, "api_key": "dummy"}
    client, _ = make_client(lambda *a: None)
    registry = ProviderRegistry.from_settings(settings, client)
    assert [p.name for p in registry.enabled()] == ["modrinth"]


def test_status_line_wording() -> None:
    """数据源状态文案（PRD §5.2）。"""
    client, _ = make_client(lambda *a: None)
    registry = ProviderRegistry.from_settings(Settings(), client)
    modrinth, curseforge = registry.status_line()
    assert modrinth == "Modrinth 已启用"
    assert curseforge == "CurseForge 未启用（缺少 API Key）"


def test_disabled_modrinth_is_reported() -> None:
    """把 Modrinth 关掉时文案要跟着变。"""
    settings = Settings()
    settings.providers["modrinth"] = {"enabled": False}
    client, _ = make_client(lambda *a: None)
    registry = ProviderRegistry.from_settings(settings, client)
    assert [p.name for p in registry.enabled()] == []
    assert registry.status_line()[0] == "Modrinth 未启用"


def test_registry_by_name() -> None:
    """按名字查数据源。"""
    client, _ = make_client(lambda *a: None)
    registry = ProviderRegistry(providers=[ModrinthProvider(client)])
    assert registry.by_name("modrinth") is not None
    assert registry.by_name("nope") is None


def test_filter_versions_is_not_a_default_path() -> None:
    """防回归：三个查询方法必须是抽象方法（不许有"先拉全量再本地过滤"的默认实现）。"""
    from modcheck.providers.base import BaseProvider

    for name in ("releases_for_loader", "compat_releases", "any_for_loader"):
        assert getattr(BaseProvider, name).__isabstractmethod__ is True, name
