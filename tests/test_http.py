"""T-11 HTTP 层测试：缓存 / 退避 / 限流 / 404 空体 / 证书错误，全部离线。"""
from __future__ import annotations

from pathlib import Path

import pytest

from modcheck.cache import HttpCache
from modcheck.errors import (ProviderHTTPError, ProviderNetworkError, ProviderNotFound,
                             ProviderParseError, ProviderRateLimited)
from modcheck.providers.http import HttpConfig, HttpClient, HttpResponse, RateLimiter
from fakes import FakeClock, FakeTransport, json_response, sequence, text_response

URL = "https://api.modrinth.com/v2/project/carpet"


def make_client(handler, clock: FakeClock | None = None, *, cache: HttpCache | None = None,
                **cfg_kw: object) -> tuple[HttpClient, FakeTransport, FakeClock]:
    """组装一个可注入的客户端。"""
    fake_clock = clock or FakeClock()
    transport = FakeTransport(handler)
    cfg = HttpConfig(rate_limit_per_min=100000, **cfg_kw)  # type: ignore[arg-type]
    client = HttpClient(cfg, cache=cache, limiter=RateLimiter(cfg.rate_limit_per_min,
                                                              clock=fake_clock.clock,
                                                              sleep=fake_clock.sleep),
                        clock=fake_clock.clock, sleep=fake_clock.sleep, transport=transport)
    return client, transport, fake_clock


def test_get_json_ok_and_user_agent() -> None:
    """200 正常解析，且 User-Agent 带程序名与版本。"""
    client, transport, _ = make_client(sequence(json_response({"ok": True})))
    assert client.get_json(URL) == {"ok": True}
    assert client.stats == (1, 0)
    assert transport.calls[0].headers["User-Agent"].startswith("modcheck/")


def test_params_are_urlencoded() -> None:
    """查询参数会被正确编码（loaders 是 JSON 数组字符串）。"""
    client, transport, _ = make_client(sequence(json_response([])))
    client.get_json(URL, {"loaders": '["fabric"]', "limit": "25"})
    url = transport.calls[0].url
    assert "loaders=%5B%22fabric%22%5D" in url
    assert "limit=25" in url


def test_cache_hit_does_not_request(tmp_path: Path) -> None:
    """缓存命中不发请求、不消耗令牌，并计入 cache_hits。"""
    cache = HttpCache(tmp_path)
    client, transport, _ = make_client(sequence(json_response({"n": 1})), cache=cache)
    assert client.get_json(URL) == {"n": 1}
    assert client.get_json(URL) == {"n": 1}
    assert transport.count == 1
    assert client.stats == (1, 1)


def test_post_cache_key_includes_body(tmp_path: Path) -> None:
    """回归（主 Agent 抓到的 P0）：同 URL、不同 payload 绝不能互相命中缓存。

    指纹反查是批量 POST，第 2 批若命中第 1 批的缓存，后面的模组会被安上错误项目。
    """
    cache = HttpCache(tmp_path)
    payloads = [{"hashes": ["aaaa"], "algorithm": "sha1"},
                {"hashes": ["bbbb"], "algorithm": "sha1"}]
    seen: list[bytes | None] = []

    def handler(method: str, url: str, data: bytes | None, index: int) -> object:
        seen.append(data)
        return json_response({"batch": index})

    client, transport, _ = make_client(handler, cache=cache)
    first = client.post_json(URL, payloads[0])
    second = client.post_json(URL, payloads[1])
    assert first == {"batch": 1}
    assert second == {"batch": 2}          # 不是第 1 批的缓存
    assert transport.count == 2            # 第二次真的发了请求
    assert client.stats == (2, 0)
    # 真正相同的 payload 仍然该命中缓存
    assert client.post_json(URL, payloads[0]) == {"batch": 1}
    assert transport.count == 2
    assert client.stats == (2, 1)
    # 字段顺序不同但语义相同 -> 同一条缓存
    assert client.post_json(URL, {"algorithm": "sha1", "hashes": ["aaaa"]}) == {"batch": 1}
    assert transport.count == 2


def test_404_empty_body_is_not_parsed() -> None:
    """基线实测：404 的响应体是空的，绝不能直接 json.loads。"""
    client, transport, _ = make_client(sequence(HttpResponse(status=404, headers={}, body=b"")))
    with pytest.raises(ProviderNotFound):
        client.get_json(URL)
    assert transport.count == 1  # 不重试


def test_404_with_body_still_not_found() -> None:
    """404 带响应体（不同 CDN 行为）同样按"没找到"处理。"""
    client, _, _ = make_client(sequence(text_response("not found", status=404)))
    with pytest.raises(ProviderNotFound):
        client.get_json(URL)


def test_429_backs_off_then_succeeds() -> None:
    """429 读 Retry-After 做全局退避，然后重试成功；绝不变成红色。"""
    responses = [HttpResponse(status=429, headers={"Retry-After": "7"}, body=b""),
                 json_response({"ok": 1})]
    client, transport, clock = make_client(sequence(*responses))
    assert client.get_json(URL) == {"ok": 1}
    assert transport.count == 2
    assert clock.total_slept >= 7


def test_429_exhausted_raises_rate_limited() -> None:
    """重试用尽 -> ProviderRateLimited（调用方据此标 ⚪ 而不是 🔴）。"""
    client, _, _ = make_client(sequence(HttpResponse(status=429, headers={}, body=b"")),
                               retries=1)
    with pytest.raises(ProviderRateLimited) as exc:
        client.get_json(URL)
    assert exc.value.status == 429


def test_429_uses_ratelimit_reset_header() -> None:
    """没有 Retry-After 时读 X-Ratelimit-Reset。"""
    responses = [HttpResponse(status=429, headers={"X-Ratelimit-Reset": "3"}, body=b""),
                 json_response({"ok": 1})]
    client, _, clock = make_client(sequence(*responses))
    assert client.get_json(URL) == {"ok": 1}
    assert clock.total_slept >= 3


def test_5xx_backoff_sequence() -> None:
    """5xx 退避序列必须是 [0.5, 1.0, 2.0]（共 4 次尝试）。"""
    client, transport, clock = make_client(sequence(json_response({}, status=500)))
    with pytest.raises(ProviderHTTPError) as exc:
        client.get_json(URL)
    assert exc.value.status == 500
    assert transport.count == 4
    assert clock.sleeps == [0.5, 1.0, 2.0]


def test_5xx_then_success() -> None:
    """5xx 之后成功：只退避一次。"""
    responses = [json_response({}, status=503), json_response({"ok": 1})]
    client, _, clock = make_client(sequence(*responses))
    assert client.get_json(URL) == {"ok": 1}
    assert clock.sleeps == [0.5]


def test_network_error_backoff_then_raise() -> None:
    """网络错误退避重试后用尽 -> ProviderNetworkError（retryable=True）。"""
    error = ProviderNetworkError("boom")
    client, transport, clock = make_client(sequence(error, error, error, error))
    with pytest.raises(ProviderNetworkError):
        client.get_json(URL)
    assert clock.sleeps == [0.5, 1.0, 2.0]
    assert transport.count == 4


def test_certificate_error_is_not_retried() -> None:
    """证书错误重试没有意义，一次就失败。"""
    error = ProviderNetworkError("cert", code="CERT", retryable=False)
    client, transport, clock = make_client(sequence(error))
    with pytest.raises(ProviderNetworkError):
        client.get_json(URL)
    assert transport.count == 1
    assert clock.sleeps == []


def test_403_is_not_retried() -> None:
    """其它 4xx 不重试。"""
    client, transport, _ = make_client(sequence(text_response("denied", status=403)))
    with pytest.raises(ProviderHTTPError) as exc:
        client.get_json(URL)
    assert exc.value.status == 403
    assert transport.count == 1


def test_bad_json_raises_parse_error() -> None:
    """响应不是 JSON -> ProviderParseError。"""
    client, _, _ = make_client(sequence(text_response("{not json")))
    with pytest.raises(ProviderParseError):
        client.get_json(URL)


def test_empty_body_raises_parse_error() -> None:
    """200 但响应体为空 -> ProviderParseError。"""
    client, _, _ = make_client(sequence(HttpResponse(status=200, body=b"")))
    with pytest.raises(ProviderParseError):
        client.get_json(URL)


def test_body_too_large_is_rejected() -> None:
    """响应体超上限 -> ProviderParseError（防御超大响应）。"""
    client, _, _ = make_client(sequence(text_response("x" * 100)), max_body_bytes=10)
    with pytest.raises(ProviderParseError):
        client.get_json(URL)


def test_use_cache_false_bypasses_cache(tmp_path: Path) -> None:
    """--refresh：忽略缓存但仍写入新结果。"""
    cache = HttpCache(tmp_path)
    client, transport, _ = make_client(sequence(json_response({"n": 1})), cache=cache)
    client.get_json(URL)
    client.use_cache = False
    client.get_json(URL)
    assert transport.count == 2
    assert client.stats == (2, 0)  # 绕过缓存时不检查、不计数


def test_refresh_style_bypass_counts_only_requests(tmp_path: Path) -> None:
    """关掉缓存后不再计命中次数。"""
    cache = HttpCache(tmp_path)
    client, transport, _ = make_client(sequence(json_response({"n": 1})), cache=cache)
    client.use_cache = False
    client.get_json(URL)
    client.get_json(URL)
    assert transport.count == 2
    assert client.stats == (2, 0)


def test_rate_limiter_sliding_window() -> None:
    """滑动窗口：窗口内放行满 2 个之后，第 3 次要等到最早那次滑出 60 秒窗口。"""
    clock = FakeClock()
    limiter = RateLimiter(2, clock=clock.clock, sleep=clock.sleep)
    limiter.acquire()
    limiter.acquire()
    assert clock.sleeps == []
    limiter.acquire()
    assert clock.sleeps == [60.0]   # 窗口长度，而不是令牌桶的 30 秒补充间隔


def test_rate_limiter_pause() -> None:
    """pause() 之后的 acquire 会睡够暂停时间。"""
    clock = FakeClock()
    limiter = RateLimiter(1000, clock=clock.clock, sleep=clock.sleep)
    limiter.pause(5)
    limiter.acquire()
    assert clock.total_slept >= 5


def test_reset_stats() -> None:
    """统计可清零。"""
    client, _, _ = make_client(sequence(json_response({})))
    client.get_json(URL)
    assert client.stats == (1, 0)
    client.reset_stats()
    assert client.stats == (0, 0)
