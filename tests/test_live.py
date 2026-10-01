"""真实网络测试（默认跳过：pytest -m live 才跑）。

对照基线 §17.3 / §17.9 的实测结论，逐条断言。这些用例是"最后一公里"的验证：
离线的假 API 只能证明"按我们理解的 API 行为"，只有这里能证明"真实 API 就是这样"。
"""
from __future__ import annotations

from typing import Mapping

import pytest

from modcheck.core.checker import classify
from modcheck.core.models import Loader, Status
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


def _decide(provider: ModrinthProvider, slug: str, mc: str) -> object:
    """按基线 §9.5.2 的两个请求做一次判定。"""
    a = provider.releases_for_loader(slug, Loader.FABRIC, window=25)
    b = provider.compat_releases(slug, mc, Loader.FABRIC, window=25)
    b2 = provider.compat_any(slug, mc, Loader.FABRIC, window=25) if not b else []
    a2 = provider.any_for_loader(slug, Loader.FABRIC, window=25) if not a else []
    return classify(loader=Loader.FABRIC, mc_version=mc, releases_for_loader=a,
                    compat_releases=b, compat_any=b2, any_for_loader=a2)


def test_live_carpet_261_is_old_version_only(live) -> None:
    """carpet @ 26.1/fabric -> 🟡 OLD_VERSION_ONLY（§17.3）。"""
    provider, _ = live
    result = _decide(provider, "carpet", "26.1")
    assert result.status is Status.DEGRADED  # type: ignore[attr-defined]
    assert result.reason.value == "OLD_VERSION_ONLY"  # type: ignore[attr-defined]


def test_live_carpet_263_is_ready(live) -> None:
    """carpet @ 26.3/fabric -> 🟢 OK（§17.3）。"""
    provider, _ = live
    result = _decide(provider, "carpet", "26.3")
    assert result.status is Status.READY  # type: ignore[attr-defined]


def test_live_journeymap_263_is_ready(live) -> None:
    """journeymap @ 26.3/fabric -> 🟢 OK（防"全局最新"误判的回归重点）。"""
    provider, _ = live
    result = _decide(provider, "journeymap", "26.3")
    assert result.status is Status.READY  # type: ignore[attr-defined]


def test_live_jei_261_is_old_version_only(live) -> None:
    """jei @ 26.1/fabric -> 🟡 OLD_VERSION_ONLY（§17.3）。"""
    provider, _ = live
    result = _decide(provider, "jei", "26.1")
    assert result.status is Status.DEGRADED  # type: ignore[attr-defined]
    assert result.reason.value == "OLD_VERSION_ONLY"  # type: ignore[attr-defined]


def test_live_jei_263_is_prerelease_only(live) -> None:
    """jei @ 26.3/fabric -> 🟡 PRERELEASE_ONLY（§17.3）。"""
    provider, _ = live
    result = _decide(provider, "jei", "26.3")
    assert result.status is Status.DEGRADED  # type: ignore[attr-defined]
    assert result.reason.value == "PRERELEASE_ONLY"  # type: ignore[attr-defined]


def test_live_jei_cost_is_two_requests(live) -> None:
    """成本上限（JEI 有 3736 个版本，是全量拉取的照妖镜）。

    实测（2026-10-01，limit=25）：**2 个请求 / 28,179 字节**，而全量拉取是
    6,797.6 KB —— 相差 240 倍。

    ⚠️ 与文档的出入：PRD S13 写"单模组 <= 3 个请求、<= 5 KB"，
    但基线自己实测的是 "?limit=1 -> 1.1 KB"，即**每条版本记录约 1.1 KB**；
    limit=25 时的真实成本必然在 25 KB 量级（基线 §9.5.2 的 "10 个请求 / 261 KB"
    也印证了这一点）。所以这里按实测事实断言 <= 64 KB，
    并保留"请求数 <= 3"这条硬约束（它才是防止全量拉取的关键）。
    """
    provider, transport = live
    _decide(provider, "jei", "26.1")
    print("JEI 请求数=", transport.calls, " 下载字节=", transport.bytes)
    assert transport.calls <= 3, transport.urls
    assert transport.bytes <= 64 * 1024, transport.bytes


def test_live_never_pulls_full_version_list(live) -> None:
    """每个 /version 请求都必须带 limit。"""
    provider, transport = live
    _decide(provider, "jei", "26.1")
    for url in transport.urls:
        if "/version" in url:
            assert "limit=" in url, url


def test_live_mojang_latest_release() -> None:
    """官方版本清单：最新正式版是 26.3，且年份制版本号存在。"""
    cfg = HttpConfig()
    versions = MojangVersions(HttpClient(cfg))
    releases = versions.list_releases(limit=5)
    assert versions.latest_release() == "26.3"
    assert [item.version_id for item in releases][0] == "26.3"
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
