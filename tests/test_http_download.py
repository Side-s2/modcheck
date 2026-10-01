"""R3-B01 / R3-B12：HttpClient.download（流式 + sha1 + .part 原子落地 + 共用限速器）。

全程离线：假 stream transport + 假 clock，不会真的发请求、也不会真的等待。
覆盖的边界（PRD §14.2 / §14.5）：成功、sha1 不符、403/404、429、中途断网、
写盘失败、超时参数、进度回调、限速器名额与请求数一致、下载计入 stats()。
"""
from __future__ import annotations

import hashlib
import io
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterator, Mapping

import pytest

from fakes import FakeClock
from modcheck.errors import (ProviderHTTPError, ProviderNetworkError, ProviderRateLimited,
                             ProviderVerifyError)
from modcheck.providers.http import (MAX_DOWNLOAD_RATE_RETRIES, STREAM_CHUNK, HttpConfig,
                                     HttpClient, RateLimiter, StreamResponse,
                                     default_stream_transport)

URL = "https://cdn.modrinth.com/data/carpet/versions/v1/carpet-26.3.jar"
PAYLOAD = bytes(range(256)) * 300          # 76800 字节：跨多个 64 KB 块


def sha1_of(data: bytes) -> str:
    """期望的 sha1（与实现无关的第二实现，避免"自己验自己"）。"""
    return hashlib.sha1(data).hexdigest()


class CountingLimiter:
    """假限速器：只数 acquire 次数并记录 pause，不真的等待。"""

    def __init__(self) -> None:
        self.calls = 0
        self.pauses: list[float] = []

    def acquire(self) -> None:
        """取一个名额。"""
        self.calls += 1

    def pause(self, seconds: float) -> None:
        """记录全局暂停。"""
        self.pauses.append(round(float(seconds), 6))


class FakeStreamTransport:
    """假流式 transport：按顺序返回注入的响应（用完一直重复最后一个）。"""

    def __init__(self, *responses: StreamResponse | Exception) -> None:
        self.responses: list[StreamResponse | Exception] = list(responses)
        self.calls: list[tuple[str, Mapping[str, str], float]] = []

    def __call__(self, url: str, headers: Mapping[str, str], timeout: float) -> StreamResponse:
        self.calls.append((url, dict(headers), timeout))
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        result = self.responses[index]
        if isinstance(result, Exception):
            raise result
        return result

    @property
    def count(self) -> int:
        """请求次数。"""
        return len(self.calls)


def chunks_of(payload: bytes, size: int) -> list[bytes]:
    """把 payload 切成固定大小的块。"""
    return [payload[start:start + size] for start in range(0, len(payload), size)] or [b""]


def make_stream(payload: bytes, *, status: int = 200, headers: Mapping[str, str] | None = None,
                size: int = 1024, close_flag: list[bool] | None = None,
                fail_after: int | None = None, fail_with: Exception | None = None,
                on_yield=None) -> StreamResponse:
    """造一个流式响应。

    参数：
        fail_after: 产出这么多块之后抛 fail_with（模拟中途断网）。
        close_flag: 生成器被关闭时往里追加 True（验证连接有没有被关掉）。
        on_yield: 产出每一块之前调一次（用来证明消费是**逐块推进**的，
            而不是"先把整个响应读完再写盘"）。
    """
    blocks = chunks_of(payload, size)

    def generate() -> Iterator[bytes]:
        try:
            for index, block in enumerate(blocks):
                if fail_after is not None and index >= fail_after:
                    raise fail_with or ProviderNetworkError("断网")
                if on_yield is not None:      # 产出之前：消费者这时最多处理到上一块
                    on_yield(index)
                yield block
        finally:
            if close_flag is not None:
                close_flag.append(True)

    return StreamResponse(status=status, headers=dict(headers or {}), chunks=generate())


def make_client(*responses: StreamResponse | Exception, limiter=None,
                clock: FakeClock | None = None, **cfg_kw: object) -> tuple[HttpClient,
                                                                             FakeStreamTransport,
                                                                             CountingLimiter]:
    """组装一个只用下载通道的客户端。"""
    fake_clock = clock or FakeClock()
    transport = FakeStreamTransport(*responses)
    counting = limiter or CountingLimiter()
    cfg = HttpConfig(rate_limit_per_min=100000, **cfg_kw)  # type: ignore[arg-type]
    client = HttpClient(cfg, limiter=counting, clock=fake_clock.clock,
                        sleep=fake_clock.sleep, stream_transport=transport)
    return client, transport, counting


# ---------------------------------------------------------------- 正常路径
def test_download_writes_exact_bytes_and_replaces_part(tmp_path: Path) -> None:
    """正常下载：字节一致、返回字节数、.part 变成正式文件、没有残留。"""
    client, transport, _ = make_client(make_stream(PAYLOAD))
    dest = tmp_path / "carpet-26.3.jar"
    written = client.download(URL, dest, sha1=sha1_of(PAYLOAD))
    assert written == len(PAYLOAD)
    assert dest.read_bytes() == PAYLOAD
    assert not (tmp_path / "carpet-26.3.jar.part").exists()
    assert transport.count == 1
    assert transport.calls[0][0] == URL


def test_download_streams_instead_of_buffering(tmp_path: Path) -> None:
    """逐块推进：写第 1 块时，后面 99 块还没有被产出（否则就是把整个文件读进内存）。"""
    produced: list[int] = []
    observed: list[int] = []
    total_blocks = len(chunks_of(PAYLOAD, 1024))
    client, _, _ = make_client(make_stream(PAYLOAD, size=1024,
                                           on_yield=lambda index: produced.append(index)))
    client.download(URL, tmp_path / "big.jar",
                    on_chunk=lambda _size: observed.append(len(produced)))
    assert observed[0] == 1                   # 第一块写下去时只产出了 1 块
    assert max(observed) == total_blocks      # 最后一块时才全部产出
    assert len(produced) == total_blocks
    assert (tmp_path / "big.jar").read_bytes() == PAYLOAD


def test_download_after_previous_file_still_written(tmp_path: Path) -> None:
    """覆盖已存在的同名文件：先写 .part 再原子替换，中途不会有半个正式文件。"""
    dest = tmp_path / "mod.jar"
    dest.write_bytes(b"OLD")
    client, _, _ = make_client(make_stream(b"NEW-CONTENT"))
    client.download(URL, dest)
    assert dest.read_bytes() == b"NEW-CONTENT"
    assert not (tmp_path / "mod.jar.part").exists()


def test_download_empty_payload(tmp_path: Path) -> None:
    """0 字节也算成功（不崩、不留 .part）。"""
    client, _, _ = make_client(make_stream(b""))
    dest = tmp_path / "empty.jar"
    assert client.download(URL, dest, sha1=sha1_of(b"")) == 0
    assert dest.exists() and dest.read_bytes() == b""
    assert not (tmp_path / "empty.jar.part").exists()


def test_download_without_expected_sha1(tmp_path: Path) -> None:
    """没有 sha1 就不校验（Provider 没给 hashes 的情况）。"""
    client, _, _ = make_client(make_stream(b"whatever"))
    dest = tmp_path / "x.jar"
    assert client.download(URL, dest) == 8
    assert dest.read_bytes() == b"whatever"


def test_download_progress_callback_receives_chunk_sizes(tmp_path: Path) -> None:
    """on_chunk 每块回调一次，回调的字节数之和等于文件大小。"""
    sizes: list[int] = []
    client, _, _ = make_client(make_stream(PAYLOAD, size=4096))
    client.download(URL, tmp_path / "p.jar", on_chunk=sizes.append)
    assert sum(sizes) == len(PAYLOAD)
    assert all(size <= 4096 for size in sizes)
    assert len(sizes) == len(chunks_of(PAYLOAD, 4096))


def test_download_headers_and_timeout(tmp_path: Path) -> None:
    """下载用二进制 Accept、带 UA，并且 timeout 参数真的传下去了。"""
    client, transport, _ = make_client(make_stream(b"x"))
    client.download(URL, tmp_path / "h.jar", timeout=3.5)
    _url, headers, timeout = transport.calls[0]
    assert timeout == 3.5
    assert headers["Accept"] == "application/octet-stream"
    assert headers["User-Agent"].startswith("modcheck/")
    client.download(URL, tmp_path / "h2.jar")
    assert transport.calls[1][2] == client.cfg.timeout


# ---------------------------------------------------------------- sha1 校验
def test_download_sha1_mismatch_raises_and_removes_part(tmp_path: Path) -> None:
    """sha1 不符：抛 ProviderVerifyError，坏文件删掉，正式文件不存在。"""
    dest = tmp_path / "bad.jar"
    client, _, _ = make_client(make_stream(b"corrupted-content"))
    with pytest.raises(ProviderVerifyError):
        client.download(URL, dest, sha1=sha1_of(b"expected-content"))
    assert not dest.exists()
    assert not (tmp_path / "bad.jar.part").exists()


def test_download_sha1_mismatch_never_overwrites_existing_file(tmp_path: Path) -> None:
    """校验失败绝不能动用户已经有的同名文件（先写 .part 的意义就在这里）。"""
    dest = tmp_path / "keep.jar"
    dest.write_bytes(b"USER-OLD-FILE")
    client, _, _ = make_client(make_stream(b"broken"))
    with pytest.raises(ProviderVerifyError):
        client.download(URL, dest, sha1="0" * 40)
    assert dest.read_bytes() == b"USER-OLD-FILE"
    assert not (tmp_path / "keep.jar.part").exists()


def test_download_accepts_uppercase_sha1(tmp_path: Path) -> None:
    """期望值大小写不敏感（不同数据源的大小写习惯不同）。"""
    client, _, _ = make_client(make_stream(b"payload"))
    client.download(URL, tmp_path / "u.jar", sha1=sha1_of(b"payload").upper())


# ---------------------------------------------------------------- HTTP 状态码
def test_download_404_raises_http_error(tmp_path: Path) -> None:
    """404 -> ProviderHTTPError（直链拿不到就是拿不到），不留文件。"""
    client, transport, _ = make_client(make_stream(b"", status=404))
    with pytest.raises(ProviderHTTPError) as exc:
        client.download(URL, tmp_path / "gone.jar")
    assert exc.value.status == 404
    assert transport.count == 1                     # 不重试
    assert not (tmp_path / "gone.jar.part").exists()


def test_download_403_raises_http_error(tmp_path: Path) -> None:
    """403 同样是非 2xx，直接失败且不留 .part。"""
    client, _, _ = make_client(make_stream(b"denied", status=403))
    with pytest.raises(ProviderHTTPError) as exc:
        client.download(URL, tmp_path / "denied.jar")
    assert exc.value.status == 403
    assert not (tmp_path / "denied.jar.part").exists()


def test_download_5xx_is_not_retried_inside(tmp_path: Path) -> None:
    """5xx 不在这里重试（重试由 core/downloader.download_all 统一管）。"""
    client, transport, _ = make_client(make_stream(b"", status=503))
    with pytest.raises(ProviderHTTPError) as exc:
        client.download(URL, tmp_path / "s.jar")
    assert exc.value.status == 503
    assert transport.count == 1


def test_download_closes_stream_on_error_status(tmp_path: Path) -> None:
    """状态码不是 2xx 时也要把连接关掉（否则大批失败会泄漏连接）。"""
    closed: list[bool] = []
    response = StreamResponse(status=500, chunks=iter(()), closer=lambda: closed.append(True))
    client, _, _ = make_client(response)
    with pytest.raises(ProviderHTTPError):
        client.download(URL, tmp_path / "c.jar")
    assert closed == [True]


def test_download_closes_stream_on_rate_limit(tmp_path: Path) -> None:
    """429 也走同一条清理路径（每次重试前都要关掉上一次的连接）。"""
    closed: list[bool] = []
    limited = StreamResponse(status=429, chunks=iter(()), closer=lambda: closed.append(True))
    client, _, _ = make_client(limited, make_stream(b"ok"))
    client.download(URL, tmp_path / "r.jar")
    assert closed == [True]


# ---------------------------------------------------------------- 429 限流
def test_download_429_pauses_then_succeeds(tmp_path: Path) -> None:
    """429：按 Retry-After 全局暂停后重来，最终成功；不算业务重试。"""
    responses = [make_stream(b"", status=429, headers={"Retry-After": "7"}),
                 make_stream(PAYLOAD)]
    client, transport, limiter = make_client(*responses)
    dest = tmp_path / "limited.jar"
    assert client.download(URL, dest, sha1=sha1_of(PAYLOAD)) == len(PAYLOAD)
    assert transport.count == 2
    assert limiter.pauses == [7.0]
    assert client.rate_limited == 1
    assert dest.read_bytes() == PAYLOAD


def test_download_429_gives_up_after_cap(tmp_path: Path) -> None:
    """一直 429：有硬上限（不然就是一个死循环），且不留 .part。"""
    client, transport, limiter = make_client(make_stream(b"", status=429))
    with pytest.raises(ProviderRateLimited) as exc:
        client.download(URL, tmp_path / "always.jar")
    assert exc.value.status == 429
    assert transport.count == MAX_DOWNLOAD_RATE_RETRIES + 1
    assert len(limiter.pauses) == MAX_DOWNLOAD_RATE_RETRIES + 1
    assert not (tmp_path / "always.jar.part").exists()


def test_download_429_part_removed_between_attempts(tmp_path: Path) -> None:
    """第二次尝试前，第一次留下的 .part 必须先被清掉（不能续写坏数据）。"""
    part = tmp_path / "half.jar.part"
    part.write_bytes(b"OLD-HALF")
    responses = [make_stream(b"", status=429), make_stream(b"FRESH")]
    client, _, _ = make_client(*responses)
    client.download(URL, tmp_path / "half.jar")
    assert (tmp_path / "half.jar").read_bytes() == b"FRESH"
    assert not part.exists()


# ---------------------------------------------------------------- 异常路径
def test_download_midstream_network_error_leaves_no_part(tmp_path: Path) -> None:
    """中途断网：抛 ProviderNetworkError，.part 一个都不留。"""
    client, _, _ = make_client(make_stream(PAYLOAD, size=1024, fail_after=2))
    dest = tmp_path / "cut.jar"
    with pytest.raises(ProviderNetworkError):
        client.download(URL, dest)
    assert not dest.exists()
    assert not (tmp_path / "cut.jar.part").exists()


def test_download_transport_open_error_leaves_no_part(tmp_path: Path) -> None:
    """连不上：transport 直接抛领域异常，同样不留 .part。"""
    client, _, _ = make_client(ProviderNetworkError("connection refused"))
    with pytest.raises(ProviderNetworkError):
        client.download(URL, tmp_path / "n.jar")
    assert not (tmp_path / "n.jar.part").exists()


def test_download_write_failure_leaves_no_part(tmp_path: Path, monkeypatch) -> None:
    """磁盘满 / 没有权限：OSError 冒泡（由 download_all 记成"写不进去"），不留 .part。"""
    def explode(self, *args, **kwargs):
        if args and args[0] == "wb":
            raise OSError(28, "No space left on device")
        return real_open(self, *args, **kwargs)

    real_open = Path.open
    monkeypatch.setattr(Path, "open", explode)
    client, _, _ = make_client(make_stream(b"x" * 10))
    with pytest.raises(OSError):
        client.download(URL, tmp_path / "full.jar")
    monkeypatch.setattr(Path, "open", real_open)
    assert not (tmp_path / "full.jar.part").exists()


def test_download_partial_write_failure_cleans_up(tmp_path: Path) -> None:
    """写到一半磁盘满：已经写进 .part 的半截文件必须被删掉。"""
    real_open = Path.open
    dest = tmp_path / "half.jar"

    class FlakyHandle:
        """写了 4 KB 之后开始报磁盘满的真文件句柄替身。"""

        def __init__(self, handle) -> None:
            self._handle = handle
            self._written = 0

        def write(self, data: bytes) -> int:
            self._written += len(data)
            if self._written > 4096:
                raise OSError(28, "No space left on device")
            return self._handle.write(data)

        def __enter__(self) -> "FlakyHandle":
            return self

        def __exit__(self, *exc) -> None:
            self._handle.close()

    def flaky(self, *args, **kwargs):
        handle = real_open(self, *args, **kwargs)
        return FlakyHandle(handle) if args and args[0] == "wb" else handle

    import unittest.mock as mock

    with mock.patch.object(Path, "open", flaky):
        client, _, _ = make_client(make_stream(PAYLOAD, size=1024))
        with pytest.raises(OSError):
            client.download(URL, dest)
    assert not dest.exists()
    assert not (tmp_path / "half.jar.part").exists()


def test_download_missing_target_directory_is_oserror(tmp_path: Path) -> None:
    """目标目录不存在：OSError（下载永远不自己建目录，建目录是调用方的事）。"""
    client, _, _ = make_client(make_stream(b"x"))
    with pytest.raises(OSError):
        client.download(URL, tmp_path / "nope" / "x.jar")


def test_download_is_reusable_after_failure(tmp_path: Path) -> None:
    """一次失败不影响下一次下载（客户端不残留状态）。"""
    client, _, _ = make_client(make_stream(b"", status=404), make_stream(b"OK"))
    with pytest.raises(ProviderHTTPError):
        client.download(URL, tmp_path / "a.jar")
    assert client.download(URL, tmp_path / "b.jar") == 2
    assert (tmp_path / "b.jar").read_bytes() == b"OK"


# ---------------------------------------------------------------- 真实流式 transport
class FakeUrllibResponse:
    """urllib 响应对象的替身（实现里只用到 status / headers / read / close）。"""

    def __init__(self, payload: bytes, *, status: int = 200,
                 fail_after: int | None = None) -> None:
        self.status = status
        self.headers = {"Content-Type": "application/java-archive"}
        self.fail_after = fail_after
        self.closed = False
        self.reads = 0
        self._buffer = io.BytesIO(payload)

    def read(self, size: int = -1) -> bytes:
        """按块读；fail_after 次之后模拟连接被复位。"""
        self.reads += 1
        if self.fail_after is not None and self.reads > self.fail_after:
            raise OSError("connection reset by peer")
        return self._buffer.read(size)

    def close(self) -> None:
        """关闭连接。"""
        self.closed = True


def test_default_stream_transport_reads_in_chunks_and_closes() -> None:
    """真实 transport：按块读、读完关连接（不发真请求）。"""
    response = FakeUrllibResponse(PAYLOAD)
    transport = default_stream_transport(HttpConfig())
    import unittest.mock as mock

    with mock.patch.object(urllib.request, "build_opener", lambda *h: _Opener(response)):
        stream = transport(URL, {"User-Agent": "x"}, 5.0)
        assert stream.status == 200
        assert b"".join(stream.chunks) == PAYLOAD
    assert response.closed is True
    assert response.reads > 1                     # 不是一次性 read()


class _Opener:
    """最小的 opener 替身。"""

    def __init__(self, result: object) -> None:
        self.result = result
        self.requests: list[object] = []

    def open(self, request, timeout=None):        # noqa: ANN001 - 替身
        self.requests.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_default_stream_transport_sets_headers_and_timeout() -> None:
    """真请求带 UA、不带 data，且 timeout 真的传给了 urllib。"""
    response = FakeUrllibResponse(b"x")
    opener = _Opener(response)
    cfg = HttpConfig(user_agent="modcheck/test")
    import unittest.mock as mock

    with mock.patch.object(urllib.request, "build_opener", lambda *h: opener):
        stream = default_stream_transport(cfg)(URL, {"User-Agent": cfg.user_agent}, 7.5)
        list(stream.chunks)
    request = opener.requests[0]
    assert request.get_method() == "GET"
    assert request.headers["User-agent"] == "modcheck/test"
    assert request.data is None


def test_default_stream_transport_uses_proxy_when_configured() -> None:
    """配了代理就走代理（与 API 那条路一致）。"""
    response = FakeUrllibResponse(b"x")
    captured: list[object] = []

    def fake_build_opener(*handlers):
        captured.extend(handlers)
        return _Opener(response)

    import unittest.mock as mock

    cfg = HttpConfig(proxy="http://127.0.0.1:7890")
    with mock.patch.object(urllib.request, "build_opener", fake_build_opener):
        list(default_stream_transport(cfg)(URL, {}, 5.0).chunks)
    assert any(isinstance(handler, urllib.request.ProxyHandler) for handler in captured)


def test_default_stream_transport_returns_status_instead_of_raising() -> None:
    """HTTP 错误状态正常返回（403/404/429 由下载逻辑判断），不在这里抛。"""
    error = urllib.error.HTTPError(URL, 404, "Not Found", {}, None)  # type: ignore[arg-type]
    opener = _Opener(error)
    import unittest.mock as mock

    with mock.patch.object(urllib.request, "build_opener", lambda *h: opener):
        stream = default_stream_transport(HttpConfig())(URL, {}, 5.0)
    assert stream.status == 404
    assert list(stream.chunks) == []


def test_default_stream_transport_maps_connection_error() -> None:
    """连不上 -> ProviderNetworkError（领域异常，调用方据此重试/记失败）。"""
    opener = _Opener(urllib.error.URLError(OSError("connection refused")))
    import unittest.mock as mock

    with mock.patch.object(urllib.request, "build_opener", lambda *h: opener):
        with pytest.raises(ProviderNetworkError):
            default_stream_transport(HttpConfig())(URL, {}, 5.0)


def test_default_stream_transport_midstream_error_and_close() -> None:
    """读到一半断网：抛 ProviderNetworkError 且连接被关掉。"""
    response = FakeUrllibResponse(PAYLOAD, fail_after=1)
    import unittest.mock as mock

    with mock.patch.object(urllib.request, "build_opener", lambda *h: _Opener(response)):
        stream = default_stream_transport(HttpConfig())(URL, {}, 5.0)
        with pytest.raises(ProviderNetworkError):
            list(stream.chunks)
    assert response.closed is True


# ---------------------------------------------------------------- 限速器 / 统计
def test_download_uses_limiter_once_per_request(tmp_path: Path) -> None:
    """限速器调用次数 == 真实请求次数（含被 429 挡回的那次）。"""
    responses = [make_stream(b"", status=429), make_stream(b"", status=429), make_stream(b"ok")]
    client, transport, limiter = make_client(*responses)
    client.download(URL, tmp_path / "l.jar")
    assert limiter.calls == transport.count == 3


def test_download_counts_into_stats(tmp_path: Path) -> None:
    """stats() 的请求数必须包含下载（PRD §14.3 的"共用一个计数器"）。"""
    client, transport, limiter = make_client(make_stream(b"abc"))
    assert client.stats == (0, 0)
    client.download(URL, tmp_path / "s.jar")
    assert client.stats[0] == 1
    assert limiter.calls == 1
    client.reset_stats()
    assert client.stats == (0, 0)


#: R3-B12 的口径：任意 60 秒窗口内请求数 <= 240
WINDOW: float = 60.0
LIMIT: int = 240


class RecordingLimiter:
    """记录每次放行时刻的真限速器（用于验证"混合发起"也守同一个窗口）。"""

    def __init__(self, inner: RateLimiter, clock) -> None:
        self.inner = inner
        self.clock = clock
        self.stamps: list[float] = []

    def acquire(self) -> None:
        """取名额并记下放行时刻。"""
        self.inner.acquire()
        self.stamps.append(self.clock())

    def pause(self, seconds: float) -> None:
        """转发全局暂停。"""
        self.inner.pause(seconds)


def test_shared_limiter_caps_mixed_api_and_download_requests(tmp_path: Path) -> None:
    """R3-B12：API 请求与下载混在一起发 500 次，任意 60 秒窗口 <= 240。

    如果下载另起一个限速器，这里会看到 480/分钟 —— 也就是"随机失败"的来源。
    """
    from fakes import FakeTransport, json_response

    clock = FakeClock()
    inner = RateLimiter(LIMIT, clock=clock.clock, sleep=clock.sleep)
    limiter = RecordingLimiter(inner, clock.clock)
    api = FakeTransport(lambda method, url, data, index: json_response({"ok": index}))
    client = HttpClient(HttpConfig(rate_limit_per_min=LIMIT), limiter=limiter,
                        clock=clock.clock, sleep=clock.sleep, transport=api,
                        stream_transport=FakeStreamTransport(make_stream(b"x" * 128)))
    for index in range(500):
        if index % 2:
            client.download(URL, tmp_path / ("m%d.jar" % index))
        else:
            client.get_json(URL + "?i=%d" % index)
    assert len(limiter.stamps) == 500
    assert client.stats[0] == 500
    for index, start in enumerate(limiter.stamps):
        inside = sum(1 for stamp in limiter.stamps[index:] if stamp - start < WINDOW)
        assert inside <= LIMIT, (index, inside)


def test_stream_chunk_is_64k() -> None:
    """读块大小是 64 KB（与 core/hashid 一致，内存占用可预期）。"""
    assert STREAM_CHUNK == 65536


def test_download_is_thread_safe_for_stats(tmp_path: Path) -> None:
    """多线程同时下载时统计不丢数（jobs=3 的真实用法）。"""
    client, transport, limiter = make_client(make_stream(b"abc"))
    threads = [threading.Thread(target=client.download,
                                args=(URL, tmp_path / ("t%d.jar" % index)))
               for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert client.stats[0] == 8
    assert limiter.calls == 8
