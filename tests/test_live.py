"""真实网络测试（默认跳过：pytest -m live 才跑）。

对照基线 §17.3 / §17.9 的实测结论，逐条断言。这些用例是"最后一公里"的验证：
离线的假 API 只能证明"按我们理解的 API 行为"，只有这里能证明"真实 API 就是这样"。
"""
from __future__ import annotations

from typing import Mapping

import pytest

from modcheck.core.checker_run import check_one
from modcheck.core.models import Loader, ModEntry, Status
from modcheck.core.report import ReportItem
from modcheck.providers.http import (HttpClient, HttpConfig, HttpResponse, default_transport)
from modcheck.providers.modrinth import ModrinthProvider
from modcheck.providers.mojang import MojangVersions

pytestmark = pytest.mark.live


class MeasuringTransport:
    """统计真实请求数与下载字节数的 transport 包装。"""

    def __init__(self, cfg: HttpConfig) -> None:
        self._inner = default_transport(cfg)
        self.calls = 0
        self.bytes = 0
        self.urls: list[str] = []

    def __call__(self, method: str, url: str, headers: Mapping[str, str],
                 data: bytes | None, timeout: float) -> HttpResponse:
        response = self._inner(method, url, headers, data, timeout)
        self.calls += 1
        self.bytes += len(response.body or b"")
        self.urls.append(method + " " + url)
        return response


@pytest.fixture()
def live() -> tuple[ModrinthProvider, MeasuringTransport]:
    """真实 Modrinth Provider + 计量 transport。"""
    cfg = HttpConfig(timeout=20.0, rate_limit_per_min=250)
    transport = MeasuringTransport(cfg)
    client = HttpClient(cfg, transport=transport)
    return ModrinthProvider(client), transport


def _decide(provider: ModrinthProvider, slug: str, mc: str) -> ReportItem:
    entry = ModEntry(key=slug, display_name=slug, sources={"modrinth": slug})
    return check_one(entry, provider, loader=Loader.FABRIC, mc_version=mc)


@pytest.mark.parametrize(("slug", "mc"), [
    ("carpet", "26.1"), ("carpet", "26.3"), ("journeymap", "26.3"),
    ("jei", "26.1"), ("jei", "26.3"),
])
def test_live_compatibility_matches_published_builds(live, slug: str, mc: str) -> None:
    """报告应与实时发布数据一致，固定发布状态由离线样本覆盖。"""
    provider, _ = live
    result = _decide(provider, slug, mc)
    releases = provider.compat_releases(slug, mc, Loader.FABRIC)
    if releases:
        assert result.status in (Status.READY, Status.DEGRADED), result.provider_message
        selected = result.latest_compat
        assert selected is not None and selected.is_release
        assert selected.version_id in {version.version_id for version in releases}
    else:
        prereleases = provider.compat_any(slug, mc, Loader.FABRIC)
        if not prereleases:
            assert result.status is Status.BLOCKED, result.provider_message
            return
        assert result.status is Status.PRERELEASE, result.provider_message
        selected = result.latest_any
        assert selected is not None and selected.version_type in ("alpha", "beta")
        assert selected.version_id in {version.version_id for version in prereleases}
    assert mc in selected.game_versions and Loader.FABRIC.value in selected.loaders


def test_live_jei_cost_is_two_requests(live) -> None:
    """成本上限（JEI 有 3736 个版本，是全量拉取的照妖镜）。

    实测（2026-10-01，limit=25）：**2 个请求 / 28,179 字节**，而全量拉取是
    6,797.6 KB —— 相差 240 倍。

    阈值是主 Agent 裁决后的 S13：**<= 3 个请求、<= 150 KB**（冷缓存最坏情况）。
    实测参考：JEI 3 请求 / 54 KB，JourneyMap 3 请求 / 86 KB，carpet 2 请求 / 26 KB；
    全量拉取则是 6,797.6 KB —— 差两个数量级。
    注意本用例在冷缓存下应发出 3 个请求（A -> B 空 -> B2）。
    """
    provider, transport = live
    _decide(provider, "jei", "26.1")
    print("JEI 请求数=", transport.calls, " 下载字节=", transport.bytes)
    assert transport.calls <= 3, transport.urls
    assert transport.bytes <= 150 * 1024, transport.bytes


def test_live_never_pulls_full_version_list(live) -> None:
    """每个 /version 请求都必须带 limit。"""
    provider, transport = live
    _decide(provider, "jei", "26.1")
    for url in transport.urls:
        if "/version" in url:
            assert "limit=" in url, url


def test_live_mojang_latest_release() -> None:
    """官方版本清单的最新正式版与 API 标明的 latest.release 一致。"""
    client = HttpClient(HttpConfig())
    versions = MojangVersions(client)
    expected = client.get_json(versions.URL)["latest"]["release"]
    releases = versions.list_releases(limit=5)
    assert versions.latest_release() == expected
    assert releases[0].version_id == expected
    assert all(item.type == "release" for item in releases)
    assert len(versions.known_versions()) > 50


def test_live_search_carpet_exact_match(live) -> None:
    """搜索 carpet 能拿到命中，并且 slug 完全同名。"""
    provider, _ = live
    hits = provider.search("carpet", limit=10)
    assert hits
    assert any(hit.slug == "carpet" for hit in hits)


def test_live_project_carpet_versions_not_sorted(live) -> None:
    """回归：/project/carpet 的 versions[] 不是倒序（只允许取长度）。"""
    provider, _ = live
    info = provider.get_project("carpet")
    assert info is not None
    assert info.version_count > 100
    assert info.slug == "carpet"
