"""测试替身：假 Provider、假 clock/sleep、假 transport（全程离线）。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from modcheck.core.models import (Loader, ProjectHit, ProjectInfo, VersionInfo)
from modcheck.providers.base import BaseProvider, filter_versions
from modcheck.providers.http import HttpResponse


class FakeProvider(BaseProvider):
    """内存数据源：可注入 hits / projects / versions / 指纹表 / 异常。

    A/B/B2/A2 四个列表可以直接注入（用于精确构造判定场景）；
    不注入时退化成对 versions 的本地过滤 —— 这对内存数据源是安全的，
    真实网络数据源**必须**自己实现带服务端过滤的查询。
    """

    name = "fake"
    display_name = "Fake"

    def __init__(self, *, hits: Sequence[ProjectHit] = (),
                 projects: dict[str, ProjectInfo] | None = None,
                 versions: dict[str, list[VersionInfo]] | None = None,
                 hash_map: dict[str, VersionInfo] | None = None,
                 raise_on: dict[str, Exception] | None = None,
                 delay: float = 0.0,
                 releases: dict[str, list[VersionInfo]] | None = None,
                 compat: dict[str, list[VersionInfo]] | None = None,
                 compat_all: dict[str, list[VersionInfo]] | None = None,
                 any_loader: dict[str, list[VersionInfo]] | None = None) -> None:
        self.hits = list(hits)
        self.projects = dict(projects or {})
        self.versions = dict(versions or {})
        self.hash_map = dict(hash_map or {})
        self.raise_on = dict(raise_on or {})
        self.delay = delay
        self.releases = dict(releases or {})
        self.compat = dict(compat or {})
        self.compat_all = dict(compat_all or {})
        self.any_loader = dict(any_loader or {})

    # ---------------------------------------------------------------- 内部
    def _maybe_raise(self, what: str) -> None:
        error = self.raise_on.get(what) or self.raise_on.get("*")
        if error is not None:
            raise error

    # ---------------------------------------------------------------- 契约
    def search(self, query: str, limit: int = 10) -> list[ProjectHit]:
        self._maybe_raise("search")
        return self.hits[:limit]

    def get_project(self, project_id: str) -> ProjectInfo | None:
        self._maybe_raise("get_project")
        return self.projects.get(project_id)

    def get_versions(self, project_id: str) -> list[VersionInfo]:
        self._maybe_raise("get_versions")
        return list(self.versions.get(project_id, ()))

    def resolve_by_hash(self, sha1s: Sequence[str]) -> dict[str, VersionInfo]:
        self._maybe_raise("resolve_by_hash")
        return {digest: self.hash_map[digest] for digest in sha1s if digest in self.hash_map}

    def releases_for_loader(self, project_id: str, loader: Loader, *, window: int = 25,
                            prerelease: bool = False) -> list[VersionInfo]:
        self._maybe_raise("releases_for_loader")
        if project_id in self.releases:
            return list(self.releases[project_id])[:window]
        return filter_versions(self.versions.get(project_id, ()), loader=loader,
                               mc_version=None, prerelease=prerelease, window=window)

    def compat_releases(self, project_id: str, mc_version: str, loader: Loader, *,
                        window: int = 25, prerelease: bool = False) -> list[VersionInfo]:
        self._maybe_raise("compat_releases")
        if project_id in self.compat:
            return list(self.compat[project_id])[:window]
        return filter_versions(self.versions.get(project_id, ()), loader=loader,
                               mc_version=mc_version, prerelease=prerelease, window=window)

    def compat_any(self, project_id: str, mc_version: str, loader: Loader, *,
                   window: int = 25) -> list[VersionInfo]:
        self._maybe_raise("compat_any")
        if project_id in self.compat_all:
            return list(self.compat_all[project_id])[:window]
        return filter_versions(self.versions.get(project_id, ()), loader=loader,
                               mc_version=mc_version, prerelease=True, window=window)

    def any_for_loader(self, project_id: str, loader: Loader, *, window: int = 25) -> list[VersionInfo]:
        self._maybe_raise("any_for_loader")
        if project_id in self.any_loader:
            return list(self.any_loader[project_id])[:window]
        return filter_versions(self.versions.get(project_id, ()), loader=loader,
                               mc_version=None, prerelease=True, window=window)


class FakeClock:
    """可控时钟 + 记录 sleep 的假睡（测试里不会真的等待）。"""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        """当前（假）时间。"""
        return self.now

    def sleep(self, seconds: float) -> None:
        """记录并推进时间。"""
        self.sleeps.append(round(float(seconds), 6))
        self.now += float(seconds)

    @property
    def total_slept(self) -> float:
        """累计睡眠秒数。"""
        return sum(self.sleeps)


@dataclass(frozen=True, slots=True)
class Call:
    """一次 transport 调用的记录。"""

    method: str
    url: str
    headers: Mapping[str, str]
    data: bytes | None
    timeout: float


#: handler 契约：(method, url, data, call_index) -> HttpResponse | Exception
Handler = Callable[[str, str, bytes | None, int], Any]


class FakeTransport:
    """假 transport：记录调用并返回注入的响应（返回 Exception 就抛出）。"""

    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.calls: list[Call] = []

    def __call__(self, method: str, url: str, headers: Mapping[str, str],
                 data: bytes | None, timeout: float) -> HttpResponse:
        self.calls.append(Call(method=method, url=url, headers=dict(headers),
                               data=data, timeout=timeout))
        result = self.handler(method, url, data, len(self.calls))
        if isinstance(result, Exception):
            raise result
        return result

    @property
    def count(self) -> int:
        """调用次数。"""
        return len(self.calls)


def json_response(payload: Any, status: int = 200,
                  headers: Mapping[str, str] | None = None) -> HttpResponse:
    """构造一个 JSON 响应。"""
    return HttpResponse(status=status, headers=dict(headers or {}),
                         body=json.dumps(payload).encode("utf-8"))


def text_response(body: bytes | str, status: int = 200,
                  headers: Mapping[str, str] | None = None) -> HttpResponse:
    """构造一个原始响应。"""
    raw = body.encode("utf-8") if isinstance(body, str) else body
    return HttpResponse(status=status, headers=dict(headers or {}), body=raw)


def sequence(*responses: Any) -> Handler:
    """按顺序返回响应；用完后一直重复最后一个。"""
    def _handler(method: str, url: str, data: bytes | None, index: int) -> Any:
        position = min(index - 1, len(responses) - 1)
        return responses[position]
    return _handler


def route(table: Mapping[str, Any], default: Any = None) -> Handler:
    """按 URL 子串路由响应（子串 -> 响应）。"""
    def _handler(method: str, url: str, data: bytes | None, index: int) -> Any:
        for key, value in table.items():
            if key in url:
                return value
        if default is None:
            raise AssertionError("no route for url: " + url)
        return default
    return _handler
