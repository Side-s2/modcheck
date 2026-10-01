"""唯一出网口：超时 / 重试退避 / 限速 / 代理 / 缓存 / 统计（基线与 PRD §7.1）。

三条实测教训已经写进实现：
  ① **404 的响应体是空的** —— 必须先判空再决定要不要 json.loads；
  ② 限流（429）要读 Retry-After / X-Ratelimit-Reset 并全局退避，
     而且**绝不能把限流说成"模组不兼容"**（那是红色误报的源头）；
  ③ 网络错误一律转成领域异常，由调用方标 ⚪ 未判定。

下载（R3-B01）复用同一个限速器与同一个统计计数器（PRD §14.3）：
一个文件 = 一个名额，下载的请求数也算进 stats()，这样"任意 60 秒窗口 ≤ 240"
对 API 与下载一起成立。下载走独立的**流式** transport（StreamResponse）——
模组 jar 动辄几十 MB，用 HttpResponse 那条路会把整个文件读进内存。

可测性：transport / stream_transport / clock / sleep 全部可注入，离线单测不会真的等待。
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Final, Iterator, Mapping

from modcheck import __version__
from modcheck.cache import HttpCache, url_key
# 临时文件后缀只允许有一份定义（core/downloader.py）：下载底座与下载编排必须用同一个
# 名字，否则"取消时清理 .part"会漏。core 是更底层的一层，providers -> core 不构成环。
from modcheck.core.downloader import PART_SUFFIX
from modcheck.errors import (ProviderHTTPError, ProviderNetworkError, ProviderNotFound,
                             ProviderParseError, ProviderRateLimited, ProviderVerifyError)
from modcheck.i18n import t

#: 单次 429 最多等多久（防御异常的 X-Ratelimit-Reset）
MAX_PAUSE_SECONDS: Final[float] = 60.0
#: acquire() 的最大迭代次数（防御性的硬上限）
MAX_ACQUIRE_STEPS: Final[int] = 10_000
#: 连续多少次"时钟没前进"就判定为无法收敛
MAX_STALLS: Final[int] = 100
#: 流式下载的读块大小（64 KB，与 core/hashid.py 一致：边读边写，不爆内存）
STREAM_CHUNK: Final[int] = 65536
#: 单次 download() 内因 429 最多重来几次。
#: 429 不算"业务重试"（PRD §14.3），但也不能无限重来 —— 这里是硬上限。
MAX_DOWNLOAD_RATE_RETRIES: Final[int] = 3


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """transport 的返回值；任何 HTTP 状态码都正常返回，只有连接层失败才抛异常。"""

    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""


#: transport 契约：(method, url, headers, data, timeout) -> HttpResponse
Transport = Callable[[str, str, Mapping[str, str], bytes | None, float], HttpResponse]


@dataclass(slots=True)
class StreamResponse:
    """流式 transport 的返回值：状态码 + 响应头 + 数据块迭代器。

    与 HttpResponse 的唯一区别：**响应体不进内存**。下载必须走这条，
    否则"下载 100 个模组"会把每个 jar 整个读进内存（PRD §14.2 明令禁止）。
    """

    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    chunks: Iterator[bytes] = field(default_factory=lambda: iter(()))
    #: 关掉底层连接的方式。为什么必须有它：chunks 是**懒**生成器，
    #: 没被迭代过的生成器调 close() 不会执行它内部的 finally ——
    #: 而 urllib 的连接在 open() 时就建立了，不关就是泄漏（404/429 大批失败时很致命）。
    closer: Callable[[], None] | None = None


#: 流式 transport 契约：(url, headers, timeout) -> StreamResponse
StreamTransport = Callable[[str, Mapping[str, str], float], StreamResponse]


@dataclass(slots=True)
class HttpConfig:
    """HTTP 层配置（默认值即 PRD 的要求）。"""

    timeout: float = 20.0
    retries: int = 3
    backoff: tuple[float, ...] = (0.5, 1.0, 2.0)
    proxy: str | None = None
    user_agent: str = "modcheck/" + __version__ + " (+https://github.com/)"
    rate_limit_per_min: int = 250          # 官方 300，留 20% 余量
    window: int = 25                       # 单次取多少条版本记录
    cache_ttl: float = 6 * 3600.0          # 秒
    max_body_bytes: int = 32 * 1024 * 1024


class RateLimiter:
    """严格滑动窗口限速器：保证**任意 window 秒内放行数 <= limit**。

    为什么不用令牌桶：满桶会让前 limit 个请求瞬间放行（实测 200 模组冷跑冲到
    399 次/分钟，直接撞官方 300 的上限，进而 429 -> 结论不可复现）。
    滑动窗口没有"突发额度"，任何 60 秒窗口的峰值都严格受限。

    ⚠️ 收敛性保证：本循环依赖注入的 clock/sleep 会推进时间。
    如果调用方给了"冻结的时钟 + 空实现的 sleep"，循环就不可能收敛，
    所以这里加了**无进展检测**：连续多次迭代时间没有前进就抛领域异常，
    绝不空转（实测过 100% CPU 空转 4.5 分钟，表现为"测试卡死"而不是失败）。
    """

    def __init__(self, per_minute: int, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 window: float = 60.0) -> None:
        self.per_minute = max(1, int(per_minute))
        self.window = float(window)
        self._stamps: deque[float] = deque()
        self._paused_until = 0.0
        self._lock = threading.Lock()
        self._clock = clock
        self._sleep = sleep

    def acquire(self) -> None:
        """取一个名额；窗口满了就等到最早那次请求滑出窗口。"""
        stalled = 0
        for _ in range(MAX_ACQUIRE_STEPS):
            now = self._clock()
            with self._lock:
                self._expire(now)
                if now < self._paused_until:
                    wait = self._paused_until - now
                else:
                    # 匀速间隔：把窗口均分，避免"首个 60 秒窗口一次性放行 limit 个"
                    # 造成的瞬时突发（实测 200 个不同项目冷跑正是它把 429 打出来的）。
                    spacing = self.window / self.per_minute
                    spacing_ok = not self._stamps or now >= self._stamps[-1] + spacing
                    if len(self._stamps) < self.per_minute and spacing_ok:
                        self._stamps.append(now)
                        return
                    wait = (self._stamps[-1] + spacing - now) if self._stamps else 1e-6
                    if len(self._stamps) >= self.per_minute:
                        wait = max(wait, self.window - (now - self._stamps[0]) + 1e-6)
            self._sleep(max(1e-6, min(wait, MAX_PAUSE_SECONDS)))
            if self._clock() <= now:
                # 时钟没前进：什么都不等就重试，必然是死循环
                stalled += 1
                if stalled >= MAX_STALLS:
                    raise ProviderRateLimited(
                        t("err.rate_limiter.stalled"), status=429, url="",
                        hint="注入的 clock/sleep 必须能推进时间")
            else:
                stalled = 0
        raise ProviderRateLimited(t("err.rate_limiter.stalled"), status=429, url="")

    def pause(self, seconds: float) -> None:
        """全局暂停（被限流时用）。"""
        seconds = max(0.0, min(float(seconds), MAX_PAUSE_SECONDS))
        with self._lock:
            self._paused_until = max(self._paused_until, self._clock() + seconds)

    def _expire(self, now: float) -> None:
        """丢掉已经滑出窗口的时间戳。"""
        while self._stamps and now - self._stamps[0] >= self.window:
            self._stamps.popleft()


def default_transport(cfg: HttpConfig) -> Transport:
    """基于 urllib 的真实 transport（代理、UA、证书错误都在这里处理）。"""

    def _send(method: str, url: str, headers: Mapping[str, str], data: bytes | None,
              timeout: float) -> HttpResponse:
        request = urllib.request.Request(url, data=data, headers=dict(headers), method=method)
        handlers: list[urllib.request.BaseHandler] = []
        if cfg.proxy:
            handlers.append(urllib.request.ProxyHandler({"http": cfg.proxy, "https": cfg.proxy}))
        opener = urllib.request.build_opener(*handlers)
        try:
            with opener.open(request, timeout=timeout) as response:
                body = response.read(cfg.max_body_bytes + 1)
                return HttpResponse(status=int(getattr(response, "status", 200)),
                                    headers=dict(response.headers), body=body)
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read(cfg.max_body_bytes + 1)
            except Exception:
                body = b""
            return HttpResponse(status=int(exc.code), headers=dict(exc.headers or {}), body=body)
        except ssl.SSLCertVerificationError as exc:
            # 证书错误重试没有意义，直接失败（PRD §7.1 第 9 条）
            raise ProviderNetworkError(t("err.cert"), code="CERT", retryable=False) from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, ssl.SSLCertVerificationError):
                raise ProviderNetworkError(t("err.cert"), code="CERT", retryable=False) from exc
            raise ProviderNetworkError(t("err.net.generic", detail=str(reason))) from exc
        except (socket.timeout, TimeoutError) as exc:
            raise ProviderNetworkError(t("err.timeout", timeout=int(timeout),
                                         retries=cfg.retries)) from exc
        except OSError as exc:
            raise ProviderNetworkError(t("err.net.generic", detail=str(exc))) from exc

    return _send


def default_stream_transport(cfg: HttpConfig) -> StreamTransport:
    """基于 urllib 的流式 transport（下载专用）。

    与 default_transport 保持同样的错误语义：**任何 HTTP 状态码都正常返回**
    （403/404/429 由下载逻辑自己判断），只有连接层失败才抛领域异常。
    """

    def _open(url: str, headers: Mapping[str, str], timeout: float) -> StreamResponse:
        request = urllib.request.Request(url, headers=dict(headers), method="GET")
        handlers: list[urllib.request.BaseHandler] = []
        if cfg.proxy:
            handlers.append(urllib.request.ProxyHandler({"http": cfg.proxy, "https": cfg.proxy}))
        opener = urllib.request.build_opener(*handlers)
        try:
            response = opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            return StreamResponse(status=int(exc.code), headers=dict(exc.headers or {}))
        except ssl.SSLCertVerificationError as exc:
            raise ProviderNetworkError(t("err.cert"), code="CERT", retryable=False) from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, ssl.SSLCertVerificationError):
                raise ProviderNetworkError(t("err.cert"), code="CERT", retryable=False) from exc
            raise ProviderNetworkError(t("err.net.generic", detail=str(reason))) from exc
        except (socket.timeout, TimeoutError) as exc:
            raise ProviderNetworkError(t("err.timeout", timeout=int(timeout),
                                         retries=cfg.retries)) from exc
        except OSError as exc:
            raise ProviderNetworkError(t("err.net.generic", detail=str(exc))) from exc
        return StreamResponse(status=int(getattr(response, "status", 200) or 200),
                              headers=dict(response.headers or {}),
                              chunks=_read_chunks(response),
                              closer=response.close)

    return _open


def _read_chunks(response: Any, chunk: int = STREAM_CHUNK) -> Iterator[bytes]:
    """按块读出响应体；读完（或中途出错）一定关掉连接。

    中途断网转成 ProviderNetworkError：调用方据此重试或记失败，
    **残留的 .part 由 HttpClient.download 的 finally 负责删掉**。
    """
    try:
        while True:
            try:
                block = response.read(chunk)
            except (socket.timeout, TimeoutError) as exc:
                raise ProviderNetworkError(t("err.net.generic",
                                             detail=str(exc) or "timeout")) from exc
            except OSError as exc:
                raise ProviderNetworkError(t("err.net.generic", detail=str(exc))) from exc
            if not block:
                return
            yield block
    finally:
        try:
            response.close()
        except Exception:
            pass


def _close_stream(response: StreamResponse) -> None:
    """关掉一个还没被读完的流（状态码不是 2xx 时必须关，否则连接泄漏）。"""
    for close in (response.closer, getattr(response.chunks, "close", None)):
        if not callable(close):
            continue
        try:
            close()
        except Exception:
            pass


class HttpClient:
    """带缓存、限速与退避的 HTTP 客户端。"""

    def __init__(self, cfg: HttpConfig, *, cache: HttpCache | None = None,
                 limiter: RateLimiter | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 transport: Transport | None = None,
                 stream_transport: StreamTransport | None = None,
                 use_cache: bool = True) -> None:
        self.cfg = cfg
        self.use_cache = use_cache
        self._cache = cache
        self._limiter = limiter or RateLimiter(cfg.rate_limit_per_min, clock=clock, sleep=sleep)
        self._sleep = sleep
        self._transport = transport or default_transport(cfg)
        #: 下载用的流式 transport（与 API 的 transport 分开：一个进内存，一个不进）
        self._stream = stream_transport or default_stream_transport(cfg)
        self._requests = 0
        self._cache_hits = 0
        #: 成功取到数据的次数（含缓存命中）—— 判断"数据源是不是整体不可用"
        self._successes = 0
        #: 收到过多少次 429（用于在报告里提示"结果可能不完整"）
        self._rate_limited = 0
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- 对外
    def get_json(self, url: str, params: Mapping[str, str] | None = None, *,
                 ttl: float | None = None, cache_key: str | None = None) -> Any:
        """GET 并解析 JSON；params 会被正确 urlencode（loaders 是 JSON 数组字符串）。"""
        full = url
        if params:
            full = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(dict(params))
        return self._request("GET", full, ttl=ttl, cache_key=cache_key)

    def post_json(self, url: str, payload: Mapping[str, Any], *,
                  ttl: float | None = None, cache_key: str | None = None) -> Any:
        """POST JSON 并解析响应。"""
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return self._request("POST", url, data=data, ttl=ttl, cache_key=cache_key)

    def download(self, url: str, dest: Path, *, sha1: str | None = None,
                 on_chunk: Callable[[int], None] | None = None,
                 timeout: float | None = None) -> int:
        """流式下载一个文件并原子落地（PRD §14.2，R3-B01）。

        参数：
            url: 直链（Modrinth 的 files[].url）。
            dest: 正式文件路径；下载过程一律写 dest + ".part"。
            sha1: 期望的 sha1；None 表示不校验。
            on_chunk: 每收到一块回调一次（参数是这一块的字节数），节流由调用方负责。
            timeout: 单次请求超时；None 用 cfg.timeout。

        返回：
            实际写入的字节数。

        抛出：
            ProviderVerifyError: sha1 不符（坏文件已删除，**不会覆盖** dest）。
            ProviderRateLimited: 一直 429（已按 Retry-After 全局暂停过）。
            ProviderHTTPError: 403/404 等非 2xx（PRD §14.2 第 4 条）。
            ProviderNetworkError: 连接失败或中途断网。
            OSError: 写盘失败（磁盘满 / 没有权限 / 目标目录不存在）。

        保证：任何异常路径都不会留下 .part（try/finally），也不会碰 dest 的旧文件。
        """
        target = Path(dest)
        part = target.with_name(target.name + PART_SUFFIX)
        rate_limits = 0
        try:
            while True:
                self._begin_request()
                response = self._stream(url, self._download_headers(),
                                        float(timeout) if timeout is not None else self.cfg.timeout)
                status = int(response.status)
                if 200 <= status < 300:
                    written, actual = self._write_part(response, part, on_chunk)
                    self._finish(part, target, actual, sha1)
                    return written
                _close_stream(response)
                if status == 429:
                    # 限流要全局退避后重来，且**不计入业务重试**（PRD §14.3）
                    with self._lock:
                        self._rate_limited += 1
                    self._limiter.pause(self._pause_seconds(response))
                    rate_limits += 1
                    if rate_limits <= MAX_DOWNLOAD_RATE_RETRIES:
                        continue
                    raise ProviderRateLimited(t("err.rate_limited"), status=status, url=url,
                                              hint=t("err.rate_limited.hint"))
                # 下载不是"找项目"：404 这里也只表示这个直链拿不到（PRD §14.2 第 4 条）
                raise ProviderHTTPError(t("err.http.status", status=status), status=status, url=url)
        finally:
            # 任何异常路径都不许留下 .part（PRD §14.2 第 5 条）。
            # 成功路径上 .part 已经被 os.replace 掉了，这里是空操作。
            _discard_part(part)

    @property
    def stats(self) -> tuple[int, int]:
        """(真实请求次数, 缓存命中次数)；**下载的请求也算在里面**（PRD §14.3）。"""
        with self._lock:
            return self._requests, self._cache_hits

    @property
    def rate_limited(self) -> int:
        """收到过的 429 次数。"""
        with self._lock:
            return self._rate_limited

    @property
    def successes(self) -> int:
        """成功取到数据的次数（含缓存命中）；用于判断数据源是否整体不可用。"""
        with self._lock:
            return self._successes

    def reset_stats(self) -> None:
        """清零统计（每次检查开始时调用）。"""
        with self._lock:
            self._requests = 0
            self._cache_hits = 0
            self._successes = 0
            self._rate_limited = 0

    # ---------------------------------------------------------------- 内部
    def _ttl(self, ttl: float | None) -> float:
        return self.cfg.cache_ttl if ttl is None else ttl

    @staticmethod
    def _cache_key_for(method: str, url: str, data: bytes | None) -> str:
        """缓存键必须包含**请求方法 + URL + 请求体**。

        ⚠️ 这里踩过一个 P0 级坑：POST 的 body 不在 URL 里，
        若只用 url 做键，批量 sha1 反查的第 2、3 批会命中第 1 批的缓存，
        把后面的模组安上**错误项目** —— 表现就是"张冠李戴"甚至"误报为绿"。
        """
        if data is None:
            return url_key(url)
        try:
            canonical = json.dumps(json.loads(data.decode("utf-8")), sort_keys=True,
                                   separators=(",", ":"))
        except (ValueError, UnicodeDecodeError):
            canonical = data.decode("utf-8", errors="replace")
        return url_key(method + "|" + url + "|" + canonical)

    def _request(self, method: str, url: str, *, data: bytes | None = None,
                 ttl: float | None = None, cache_key: str | None = None) -> Any:
        key = cache_key or self._cache_key_for(method, url, data)
        if self._cache is not None and self.use_cache:
            cached = self._cache.get(key, self._ttl(ttl))
            if cached is not None:
                with self._lock:
                    self._cache_hits += 1
                    self._successes += 1
                return cached

        headers = {
            "User-Agent": self.cfg.user_agent,
            "Accept": "application/json",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"

        attempt = 0
        while True:
            try:
                response = self._send(method, url, headers, data)
            except ProviderNetworkError as exc:
                if exc.retryable and attempt < self.cfg.retries:
                    self._sleep(self._delay(attempt))
                    attempt += 1
                    continue
                raise

            status = response.status
            if 200 <= status < 300:
                payload = self._parse(response)
                with self._lock:
                    self._successes += 1
                if self._cache is not None and self.use_cache:
                    self._cache.put(key, payload, url=url)
                return payload
            if status == 404:
                # 实测：Modrinth 的 404 响应体是空的，绝不能直接 json.loads
                raise ProviderNotFound(t("err.http.404"), code="404")
            if status == 429:
                with self._lock:
                    self._rate_limited += 1
                self._limiter.pause(self._pause_seconds(response))
                if attempt < self.cfg.retries:
                    attempt += 1
                    continue
                raise ProviderRateLimited(t("err.rate_limited"), status=status, url=url,
                                          hint=t("err.rate_limited.hint"))
            if 500 <= status < 600:
                if attempt < self.cfg.retries:
                    self._sleep(self._delay(attempt))
                    attempt += 1
                    continue
                raise ProviderHTTPError(t("err.http.5xx", status=status), status=status, url=url)
            raise ProviderHTTPError(t("err.http.status", status=status), status=status, url=url)

    def _begin_request(self) -> None:
        """取一个限速名额并计数：**API 与下载共用同一个限速器**（PRD §14.3）。

        一个文件 = 一个名额（不按字节/分片计数），所以
        "limiter.acquire() 次数 == 真实请求次数" 在两条路径上都成立。
        """
        self._limiter.acquire()
        with self._lock:
            self._requests += 1

    def _send(self, method: str, url: str, headers: Mapping[str, str],
              data: bytes | None) -> HttpResponse:
        self._begin_request()
        return self._transport(method, url, headers, data, self.cfg.timeout)

    def _download_headers(self) -> dict[str, str]:
        """下载用的请求头（直链是二进制，不能要 application/json）。"""
        return {"User-Agent": self.cfg.user_agent, "Accept": "application/octet-stream"}

    def _write_part(self, response: StreamResponse, part: Path,
                    on_chunk: Callable[[int], None] | None) -> tuple[int, str]:
        """把响应体流式写进 .part，**边写边算 sha1**（不把文件读进内存）。"""
        digest = hashlib.sha1()
        written = 0
        with Path(part).open("wb") as handle:
            for block in response.chunks:
                if not block:
                    continue
                handle.write(block)
                digest.update(block)
                written += len(block)
                if on_chunk is not None:
                    on_chunk(len(block))
        return written, digest.hexdigest()

    def _finish(self, part: Path, target: Path, actual: str, expected: str | None) -> None:
        """校验 sha1 后原子落地；校验不过**绝不**覆盖目标文件。"""
        if expected:
            want = str(expected).strip().lower()
            if want and want != actual:
                raise ProviderVerifyError(
                    t("err.download.sha1", name=Path(target).name, expected=want, actual=actual),
                    hint=t("err.download.sha1.hint"))
        os.replace(part, target)

    def _delay(self, attempt: int) -> float:
        backoff = self.cfg.backoff or (0.5,)
        return backoff[attempt] if attempt < len(backoff) else backoff[-1]

    def _parse(self, response: HttpResponse) -> Any:
        body = response.body or b""
        if len(body) > self.cfg.max_body_bytes:
            raise ProviderParseError(t("err.parse.provider"), code="BODY_TOO_LARGE")
        if not body:
            raise ProviderParseError(t("err.parse.provider"), code="EMPTY_BODY")
        try:
            return json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ProviderParseError(t("err.parse.provider"), code="BAD_JSON") from exc

    def _pause_seconds(self, response: HttpResponse | StreamResponse) -> float:
        """从响应头里取退避秒数（Retry-After 优先，其次 X-Ratelimit-Reset）。"""
        headers = {str(k).lower(): str(v) for k, v in (response.headers or {}).items()}
        for name in ("retry-after", "x-ratelimit-reset"):
            raw = headers.get(name)
            if not raw:
                continue
            try:
                value = float(raw.strip())
            except ValueError:
                continue
            if value >= 0:
                return min(value, MAX_PAUSE_SECONDS)
        return 1.0


def _discard_part(part: Path) -> None:
    """删掉残留的 .part（不存在、删不掉都不报错：清理失败不该盖住真正的错误）。"""
    try:
        Path(part).unlink(missing_ok=True)
    except OSError:
        pass


__all__ = ["HttpResponse", "StreamResponse", "Transport", "StreamTransport", "HttpConfig",
           "RateLimiter", "HttpClient", "default_transport", "default_stream_transport",
           "MAX_PAUSE_SECONDS", "MAX_DOWNLOAD_RATE_RETRIES", "STREAM_CHUNK"]
