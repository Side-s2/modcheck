"""T-12 Modrinth 测试：URL 构造、参数编码、limit 法、指纹反查、乱序陷阱。

这里用一个**模拟 Modrinth 服务端过滤行为**的假 API：
它能解析真实的查询串并做服务端过滤，所以只要 URL 编码错了就会立刻暴露。
"""
from __future__ import annotations

import json
import urllib.parse
from typing import Any, Sequence

import pytest

from conftest import load_fixture
from fakes import FakeClock, FakeTransport, json_response, route, text_response
from modcheck.core.checker import classify
from modcheck.core.models import Loader, Status
from modcheck.errors import ProviderNotFound
from modcheck.providers.http import HttpConfig, HttpClient, HttpResponse, RateLimiter
from modcheck.providers.modrinth import ModrinthProvider

BASE = "https://api.modrinth.com/v2"


def make_provider(handler) -> tuple[ModrinthProvider, FakeTransport, HttpClient]:
    """组装一个可注入的 Modrinth Provider。"""
    clock = FakeClock()
    transport = FakeTransport(handler)
    cfg = HttpConfig(rate_limit_per_min=100000)
    client = HttpClient(cfg, limiter=RateLimiter(cfg.rate_limit_per_min, clock=clock.clock,
                                                 sleep=clock.sleep),
                        clock=clock.clock, sleep=clock.sleep, transport=transport)
    return ModrinthProvider(client), transport, client


def emulated_api(versions: Sequence[dict[str, Any]], *,
                 hashes: dict[str, Any] | None = None,
                 project: dict[str, Any] | None = None,
                 search_hits: Sequence[dict[str, Any]] = ()) -> Any:
    """模拟 Modrinth：解析真实查询串并做服务端过滤。"""
    def handler(method: str, url: str, data: bytes | None, index: int) -> HttpResponse:
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path.endswith("/version_files"):
            payload = json.loads((data or b"{}").decode("utf-8"))
            table = hashes or {}
            return json_response({h: table[h] for h in payload.get("hashes", []) if h in table})
        if parsed.path.endswith("/version"):
            items = list(versions)
            if "loaders" in query:
                wanted = set(json.loads(query["loaders"][0]))
                items = [v for v in items if wanted & set(v["loaders"])]
            if "game_versions" in query:
                wanted_mc = set(json.loads(query["game_versions"][0]))
                items = [v for v in items if wanted_mc & set(v["game_versions"])]
            if "version_type" in query:
                items = [v for v in items if v["version_type"] == query["version_type"][0]]
            limit = int(query.get("limit", ["25"])[0])
            return json_response(items[:limit])
        if "/search" in parsed.path:
            return json_response({"hits": list(search_hits)})
        if "/project/" in parsed.path:
            return json_response(project or {})
        return json_response({}, status=404)
    return handler


# ---------------------------------------------------------------- URL / 编码
def test_releases_for_loader_url_encoding() -> None:
    """请求 A 的参数必须是 JSON 数组字符串并经 urlencode。"""
    provider, transport, _ = make_provider(route({"/version": json_response([])}))
    provider.releases_for_loader("carpet", Loader.FABRIC, window=25)
    url = transport.calls[0].url
    assert "loaders=%5B%22fabric%22%5D" in url
    assert "version_type=release" in url
    assert "limit=25" in url
    assert 'loaders=["fabric"]' not in url  # 绝不能手写未编码的数组


def test_compat_releases_url_encoding() -> None:
    """请求 B 额外带 game_versions。"""
    provider, transport, _ = make_provider(route({"/version": json_response([])}))
    provider.compat_releases("carpet", "26.1", Loader.FABRIC, window=25)
    url = transport.calls[0].url
    assert "game_versions=%5B%2226.1%22%5D" in url
    assert "loaders=%5B%22fabric%22%5D" in url
    assert "version_type=release" in url


def test_any_for_loader_has_no_version_type() -> None:
    """请求 A2 不过滤通道。"""
    provider, transport, _ = make_provider(route({"/version": json_response([])}))
    provider.any_for_loader("carpet", Loader.FABRIC)
    assert "version_type" not in transport.calls[0].url


def test_prerelease_drops_version_type_filter() -> None:
    """--pre 时 A/B 去掉 version_type=release。"""
    provider, transport, _ = make_provider(route({"/version": json_response([])}))
    provider.releases_for_loader("carpet", Loader.FABRIC, prerelease=True)
    provider.compat_releases("carpet", "26.3", Loader.FABRIC, prerelease=True)
    assert all("version_type" not in call.url for call in transport.calls)


def test_search_facets_and_limit() -> None:
    """搜索必须限定 project_type:mod 并带 limit。"""
    provider, transport, _ = make_provider(route({"/search": json_response({"hits": []})}))
    provider.search("carpet", limit=10)
    url = transport.calls[0].url
    assert "facets=" in url
    assert urllib.parse.quote('[["project_type:mod"]]', safe="") in url
    assert "limit=10" in url


def test_get_versions_always_sends_limit() -> None:
    """禁止全量拉取：即使不传 window 也要带 limit（默认 25）。"""
    provider, transport, _ = make_provider(route({"/version": json_response([])}))
    provider.get_versions("jei")
    assert "limit=25" in transport.calls[0].url


def test_no_request_without_limit_on_version_endpoint() -> None:
    """所有版本端点调用都必须带 limit（防全量拉取回归）。"""
    provider, transport, _ = make_provider(route({"/version": json_response([])}))
    provider.releases_for_loader("jei", Loader.FABRIC)
    provider.compat_releases("jei", "26.3", Loader.FABRIC)
    provider.any_for_loader("jei", Loader.FABRIC)
    provider.get_versions("jei")
    assert transport.count == 4
    for call in transport.calls:
        assert "/version" in call.url
        assert "limit=" in call.url


# ---------------------------------------------------------------- 项目与 404
def test_get_project_404_returns_none() -> None:
    """404（响应体为空）返回 None，不抛异常。"""
    provider, _, _ = make_provider(route({"/project/": HttpResponse(status=404, body=b"")}))
    assert provider.get_project("no-such-mod-xyz") is None


def test_get_project_uses_versions_only_for_count() -> None:
    """回归用例 15：/project 的 versions[] 只允许取长度，绝不取首条判断最新版。"""
    fixture = load_fixture("project_carpet.json")
    provider, _, _ = make_provider(route({"/project/": json_response(fixture)}))
    info = provider.get_project("carpet")
    assert info is not None
    assert info.version_count == 6
    assert info.slug == "carpet"


def test_project_versions_order_is_never_used() -> None:
    """源码级回归：禁止出现 versions[0] / 对 versions 排序的写法。"""
    # 用 AST 只看真实代码，避免被注释/文档字符串里的示例带偏
    import ast
    from pathlib import Path

    source = Path("src/modcheck/providers/modrinth.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    called = [ast.unparse(node.func) for node in calls]
    max_args = [ast.unparse(node) for node in calls if ast.unparse(node.func) == "max"]
    assert all("version" not in text for text in max_args), max_args
    assert called.count("sorted") == 1, "只允许对指纹哈希排序以稳定缓存键"
    sorted_args = [ast.unparse(node.args[0]) for node in calls
                   if ast.unparse(node.func) == "sorted"]
    assert "hashes" in sorted_args[0]
    # 不许对任何 versions 变量做下标取值（只有 len() 是允许的）
    subscripts = [ast.unparse(node.value) for node in ast.walk(tree)
                  if isinstance(node, ast.Subscript)]
    assert not any("versions" in text for text in subscripts), subscripts
    attrs = [node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)]
    assert "date_published" not in attrs, "数据源不该碰 date_published"
    assert "sort" not in attrs, "禁止对 /version 的返回原地排序（要信任 API 顺序）"


# ---------------------------------------------------------------- 指纹反查
def test_resolve_by_hash_only_returns_hits() -> None:
    """未命中的哈希不出现在返回体里（实测），只能用 key 判断而不是异常。"""
    table = load_fixture("version_files_hit.json")
    provider, transport, _ = make_provider(emulated_api([], hashes=table))
    hit = list(table)[0]
    result = provider.resolve_by_hash([hit, "f" * 40])
    assert set(result) == {hit}
    assert result[hit].version_number == "26.1"
    assert transport.calls[0].method == "POST"
    body = json.loads((transport.calls[0].data or b"{}").decode("utf-8"))
    assert body["algorithm"] == "sha1"
    assert set(body["hashes"]) == {hit, "f" * 40}


def test_resolve_by_hash_empty_input_makes_no_request() -> None:
    """空输入不发请求。"""
    provider, transport, _ = make_provider(emulated_api([], hashes={}))
    assert provider.resolve_by_hash([]) == {}
    assert transport.count == 0


def test_resolve_by_hash_all_miss() -> None:
    """全部未命中 -> 空字典，不抛异常。"""
    provider, _, _ = make_provider(emulated_api([], hashes={}))
    assert provider.resolve_by_hash(["a" * 40]) == {}


# ---------------------------------------------------------------- 端到端（离线）
def test_journeymap_same_date_four_loaders_is_ready() -> None:
    """JourneyMap 陷阱的端到端版本：4 条同版本号、同日期、不同加载器。

    服务端过滤之后，fabric 目标下 A=B=那一条 fabric 记录 -> 🟢 OK。
    """
    fixture = load_fixture("versions_journeymap_26.3.json")
    provider, transport, _ = make_provider(emulated_api(fixture, project={"id": "Pjm"}))
    a = provider.releases_for_loader("Pjm", Loader.FABRIC)
    b = provider.compat_releases("Pjm", "26.3", Loader.FABRIC)
    result = classify(loader=Loader.FABRIC, mc_version="26.3", releases_for_loader=a,
                      compat_releases=b)
    assert result.status is Status.READY
    assert result.latest_for_loader is not None
    assert "fabric" in result.latest_for_loader.loaders
    assert transport.count == 2


def test_carpet_261_fabric_is_degraded_end_to_end() -> None:
    """carpet @ 26.1/fabric：A=26.3 那条，B=26.1 那条 -> 🟡 OLD_VERSION_ONLY。"""
    fixture = (load_fixture("versions_carpet_26.3_fabric.json")
               + load_fixture("versions_carpet_26.1_fabric.json"))
    provider, _, _ = make_provider(emulated_api(fixture))
    a = provider.releases_for_loader("Pcarpet", Loader.FABRIC)
    b = provider.compat_releases("Pcarpet", "26.1", Loader.FABRIC)
    result = classify(loader=Loader.FABRIC, mc_version="26.1", releases_for_loader=a,
                      compat_releases=b)
    assert result.status is Status.DEGRADED
    assert result.latest_compat is not None
    assert result.latest_compat.version_number == "26.1"


def test_jei_263_fabric_prerelease_end_to_end() -> None:
    """jei @ 26.3/fabric：B 空、B2 有 beta -> 🟡 PRERELEASE_ONLY。"""
    fixture = load_fixture("versions_jei_26.3_fabric.json")
    dataset = fixture["releases"] + fixture["compat"] + fixture["compat_any"]
    provider, _, _ = make_provider(emulated_api(dataset))
    a = provider.releases_for_loader("Pjei", Loader.FABRIC)
    b = provider.compat_releases("Pjei", "26.3", Loader.FABRIC)
    b2 = provider.compat_any("Pjei", "26.3", Loader.FABRIC)
    assert b == []
    result = classify(loader=Loader.FABRIC, mc_version="26.3", releases_for_loader=a,
                      compat_releases=b, compat_any=b2)
    assert result.status is Status.DEGRADED
    assert result.reason.value == "PRERELEASE_ONLY"


def test_limit_keeps_payload_small() -> None:
    """limit 法必须把响应压小：造一个 500 条的大项目，单次响应仍很小。"""
    big = [{"id": f"v{i}", "project_id": "Pbig", "version_number": f"1.0.{i}",
            "name": str(i), "date_published": "2026-01-01T00:00:00Z",
            "version_type": "release", "game_versions": ["26.3"], "loaders": ["fabric"],
            "files": [{"filename": f"big-1.0.{i}.jar", "url": "u", "primary": True,
                       "size": 100, "hashes": {"sha1": "a" * 40}}]}
           for i in range(500)]
    provider, transport, _ = make_provider(emulated_api(big))
    versions = provider.releases_for_loader("Pbig", Loader.FABRIC, window=25)
    assert len(versions) == 25
    assert transport.count == 1
    assert len(transport.calls[0].url) < 200
