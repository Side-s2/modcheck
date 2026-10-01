"""Mojang 官方版本清单测试（只取 release，快照一律忽略）。"""
from __future__ import annotations

from conftest import load_fixture
from fakes import FakeClock, FakeTransport, json_response, route
from modcheck.providers.http import HttpConfig, HttpClient, RateLimiter
from modcheck.providers.mojang import MojangVersions


def make_versions() -> tuple[MojangVersions, FakeTransport]:
    """用裁剪版清单夹具组装。"""
    clock = FakeClock()
    transport = FakeTransport(route({"version_manifest_v2": json_response(load_fixture("manifest_v2.json"))}))
    cfg = HttpConfig(rate_limit_per_min=100000)
    client = HttpClient(cfg, limiter=RateLimiter(cfg.rate_limit_per_min, clock=clock.clock,
                                                 sleep=clock.sleep),
                        clock=clock.clock, sleep=clock.sleep, transport=transport)
    return MojangVersions(client), transport


def test_only_releases_and_sorted_desc() -> None:
    """只保留 release，并按发布时间从新到旧。"""
    versions, _ = make_versions()
    releases = versions.list_releases()
    assert [item.version_id for item in releases][:5] == ["26.3", "26.2", "26.1.2", "26.1.1", "26.1"]
    assert all(item.type == "release" for item in releases)
    assert "26.4-snapshot-2" not in {item.version_id for item in releases}
    assert "24w14a" not in {item.version_id for item in releases}


def test_limit_and_latest_and_known() -> None:
    """limit / latest_release / known_versions。"""
    versions, _ = make_versions()
    assert [item.version_id for item in versions.list_releases(limit=2)] == ["26.3", "26.2"]
    assert versions.latest_release() == "26.3"
    known = versions.known_versions()
    assert {"26.3", "26.1", "1.21.4"} <= known
    assert "26.4-snapshot-2" not in known


def test_memoized_single_request() -> None:
    """清单只请求一次（进程内 memo + 磁盘缓存）。"""
    versions, transport = make_versions()
    versions.list_releases()
    versions.latest_release()
    versions.known_versions()
    assert transport.count == 1
