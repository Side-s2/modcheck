"""唯一出网口：超时 / 重试退避 / 限速 / 代理 / 缓存 / 统计（基线与 PRD §7.1）。

三条实测教训已经写进实现：
  ① **404 的响应体是空的** —— 必须先判空再决定要不要 json.loads；
  ② 限流（429）要读 Retry-After / X-Ratelimit-Reset 并全局退避，
     而且**绝不能把限流说成"模组不兼容"**（那是红色误报的源头）；
  ③ 网络错误一律转成领域异常，由调用方标 ⚪ 未判定。

可测性：transport / clock / sleep 全部可注入，离线单测不会真的等待。
"""
from __future__ import annotations

import json
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Final, Mapping

from modcheck import __version__
from modcheck.cache import HttpCache, url_key
from modcheck.errors import (ProviderHTTPError, ProviderNetworkError, ProviderNotFound,
                             ProviderParseError, ProviderRateLimited)
from modcheck.i18n import t

#: 单次 429 最多等多久（防御异常的 X-Ratelimit-Reset）
MAX_PAUSE_SECONDS: Final[float] = 60.0


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """transport 的返回值；任何 HTTP 状态码都正常返回，只有连接层失败才抛异常。"""

    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""


#: transport 契约：(method, url, headers, data, timeout) -> HttpResponse
Transport = Callable[[str, str, Mapping[str, str], bytes | None, float], HttpResponse]


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
    """线程安全的令牌桶；429 时用 pause() 做全局退避。"""

    def __init__(self, per_minute: int, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.per_minute = max(1, int(per_minute))
        self._rate = self.per_minute / 60.0
        self._tokens = float(self.per_minute)
        self._last = clock()
        self._paused_until = 0.0
        self._lock = threading.Lock()
        self._clock = clock
        self._sleep = sleep

    def acquire(self) -> None:
        """取一个令牌；不够就等到够（用注入的 sleep，测试里不会真的等）。"""
        while True:
            with self._lock:
                now = self._clock()
                if now < self._paused_until:
                    wait = self._paused_until - now
                else:
                    self._refill(now)
                    if self._tokens >= 1.0:
                        self._tokens -= 1.0
                        return
                    wait = (1.0 - self._tokens) / self._rate
            self._sleep(max(0.0, min(wait, MAX_PAUSE_SECONDS)))

    def pause(self, seconds: float) -> None:
        """全局暂停（被限流时用）。"""
        seconds = max(0.0, min(float(seconds), MAX_PAUSE_SECONDS))
        with self._lock:
            self._paused_until = max(self._paused_until, self._clock() + seconds)

    def _refill(self, now: float) -> None:
        elapsed = max(0.0, now - self._last)
        self._last = now
        self._tokens = min(float(self.per_minute), self._tokens + elapsed * self._rate)


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


class HttpClient:
    """带缓存、限速与退避的 HTTP 客户端。"""

    def __init__(self, cfg: HttpConfig, *, cache: HttpCache | None = None,
                 limiter: RateLimiter | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 transport: Transport | None = None,
                 use_cache: bool = True) -> None:
        self.cfg = cfg
        self.use_cache = use_cache
        self._cache = cache
        self._limiter = limiter or RateLimiter(cfg.rate_limit_per_min, clock=clock, sleep=sleep)
        self._sleep = sleep
        self._transport = transport or default_transport(cfg)
        self._requests = 0
        self._cache_hits = 0
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

    @property
    def stats(self) -> tuple[int, int]:
        """(真实请求次数, 缓存命中次数)。"""
        with self._lock:
            return self._requests, self._cache_hits

    def reset_stats(self) -> None:
        """清零统计（每次检查开始时调用）。"""
        with self._lock:
            self._requests = 0
            self._cache_hits = 0

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
                if self._cache is not None and self.use_cache:
                    self._cache.put(key, payload, url=url)
                return payload
            if status == 404:
                # 实测：Modrinth 的 404 响应体是空的，绝不能直接 json.loads
                raise ProviderNotFound(t("err.http.404"), code="404")
            if status == 429:
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

    def _send(self, method: str, url: str, headers: Mapping[str, str],
              data: bytes | None) -> HttpResponse:
        self._limiter.acquire()
        with self._lock:
            self._requests += 1
        return self._transport(method, url, headers, data, self.cfg.timeout)

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

    def _pause_seconds(self, response: HttpResponse) -> float:
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


__all__ = ["HttpResponse", "Transport", "HttpConfig", "RateLimiter", "HttpClient",
           "default_transport", "MAX_PAUSE_SECONDS"]
