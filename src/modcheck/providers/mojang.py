"""Mojang 官方版本清单（无需 API Key，基线 §9.3）。

用途：交互式版本选择、--mc 的合法性校验、文件名解析时的 MC 版本锚点。
只取 type == "release"；快照一律忽略（本期不检查快照）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from modcheck.providers.http import HttpClient


@dataclass(frozen=True, slots=True)
class McRelease:
    """官方正式版的一条记录。"""

    version_id: str
    release_time: str
    type: str


class MojangVersions:
    """官方版本清单的读取与缓存（进程内 memo，磁盘缓存由 HttpClient 负责）。"""

    URL: Final[str] = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"

    def __init__(self, client: HttpClient, *, ttl: float = 24 * 3600.0) -> None:
        self.client = client
        self.ttl = ttl
        self._memo: list[McRelease] | None = None

    def _fetch(self) -> list[McRelease]:
        if self._memo is not None:
            return self._memo
        data = self.client.get_json(self.URL, ttl=self.ttl)
        raw = data.get("versions") if isinstance(data, dict) else None
        releases: list[McRelease] = []
        for item in raw or ():
            if not isinstance(item, dict):
                continue
            if str(item.get("type", "")) != "release":
                continue
            releases.append(McRelease(version_id=str(item.get("id", "")),
                                      release_time=str(item.get("releaseTime", "")),
                                      type="release"))
        # releaseTime 是 ISO-8601（UTC，固定宽度），字典序等于时间序，可以安全排序
        releases.sort(key=lambda item: item.release_time, reverse=True)
        self._memo = releases
        return releases

    def list_releases(self, *, limit: int | None = None) -> list[McRelease]:
        """列出全部正式版（从新到旧）；limit 给出时只取前 limit 条。"""
        releases = self._fetch()
        return releases if limit is None else releases[:max(0, int(limit))]

    def latest_release(self) -> str | None:
        """最新正式版号；取不到时返回 None。"""
        releases = self._fetch()
        return releases[0].version_id if releases else None

    def known_versions(self) -> set[str]:
        """全部正式版号（供 --mc 校验与文件名锚点）。"""
        return {item.version_id for item in self._fetch()}


__all__ = ["McRelease", "MojangVersions"]
