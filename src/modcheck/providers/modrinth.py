"""Modrinth 数据源（本期唯一实现的网络数据源）。

**必须遵守的三条禁令**（写在这里，改代码前先读一遍）：
  ❌ 不许用 GET /project/{id} 返回的 versions[] 判断"最新版" —— 实测它不是倒序
     （carpet 的前 6 条是 2022 年的，基线 §17.8）。只允许取它的长度。
  ❌ 不许对 /project/{id}/version 的返回自行排序或取 max(date_published) ——
     基线 §7 要求直接信任返回顺序（日期会并列）。
  ❌ 不许全量拉取 /project/{id}/version —— 实测 JEI 有 3736 条 / 6.8 MB。

判定只用 2~3 个"带服务端过滤 + limit"的小请求（基线 §9.5.2）：
  A  = /project/{slug}/version?loaders=["L"]&version_type=release&limit=W
  B  = ...&game_versions=["V"]&loaders=["L"]&version_type=release&limit=W
  B2 = ...&game_versions=["V"]&loaders=["L"]&limit=W        （仅当 B 为空）
  A2 = ...&loaders=["L"]&limit=W                            （仅当 A 为空）
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Final, Mapping, Sequence

from modcheck.core.models import Loader, ProjectHit, ProjectInfo, VersionInfo
from modcheck.errors import ProviderNotFound
from modcheck.providers.base import BaseProvider
from modcheck.providers.http import HttpClient


class ModrinthProvider(BaseProvider):
    """Modrinth（无需 API Key）。"""

    name = "modrinth"
    display_name = "Modrinth"
    BASE: Final[str] = "https://api.modrinth.com/v2"

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    # ---------------------------------------------------------------- 工具
    @staticmethod
    def _json_array(values: Sequence[str]) -> str:
        """loaders / game_versions 是 **JSON 数组字符串**，必须这样编码。

        实测易错点：不能手写 ?loaders=["fabric"]，要 urlencode 成
        loaders=%5B%22fabric%22%5D。
        """
        return json.dumps(list(values), separators=(",", ":"))

    def _versions(self, project_id: str, params: Mapping[str, str]) -> list[VersionInfo]:
        """请求版本列表；顺序原样保留（API 已按发布时间倒序）。"""
        url = self.BASE + "/project/" + str(project_id) + "/version"
        data = self.client.get_json(url, params)
        if not isinstance(data, list):
            return []
        return [VersionInfo.from_api(item) for item in data if isinstance(item, dict)]

    # ---------------------------------------------------------------- 契约实现
    def search(self, query: str, limit: int = 10) -> list[ProjectHit]:
        """按名字搜索；facets 限定 project_type:mod（避免搜到整合包/材质）。"""
        params = {
            "query": query,
            "limit": str(max(1, int(limit))),
            "facets": self._json_array([["project_type:mod"]]),
        }
        data = self.client.get_json(self.BASE + "/search", params)
        hits = data.get("hits") if isinstance(data, dict) else None
        if not isinstance(hits, list):
            return []
        return [ProjectHit.from_api(item, provider=self.name)
                for item in hits if isinstance(item, dict)]

    def get_project(self, project_id: str) -> ProjectInfo | None:
        """取项目详情；404（响应体为空）返回 None，不抛异常。"""
        try:
            data = self.client.get_json(self.BASE + "/project/" + str(project_id))
        except ProviderNotFound:
            return None
        if not isinstance(data, dict):
            return None
        return ProjectInfo.from_api(data)

    def get_versions(self, project_id: str, *, window: int | None = None) -> list[VersionInfo]:
        """取版本列表；**必须带 limit**，绝不无限制拉取。"""
        limit = window if window is not None else self.client.cfg.window
        return self._versions(project_id, {"limit": str(max(1, int(limit)))})

    def releases_for_loader(self, project_id: str, loader: Loader, *, window: int = 25,
                            prerelease: bool = False) -> list[VersionInfo]:
        """请求 A：目标加载器的最新版本（默认只认 release 通道）。"""
        params = {"loaders": self._json_array([loader.value]), "limit": str(max(1, int(window)))}
        if not prerelease:
            params["version_type"] = "release"
        return self._versions(project_id, params)

    def compat_releases(self, project_id: str, mc_version: str, loader: Loader, *,
                        window: int = 25, prerelease: bool = False) -> list[VersionInfo]:
        """请求 B：目标加载器 + 目标 MC 版本的版本。"""
        params = {
            "game_versions": self._json_array([mc_version]),
            "loaders": self._json_array([loader.value]),
            "limit": str(max(1, int(window))),
        }
        if not prerelease:
            params["version_type"] = "release"
        return self._versions(project_id, params)

    def any_for_loader(self, project_id: str, loader: Loader, *, window: int = 25) -> list[VersionInfo]:
        """请求 A2：只按加载器过滤（含 beta/alpha），用于区分"只有测试版"。"""
        params = {"loaders": self._json_array([loader.value]), "limit": str(max(1, int(window)))}
        return self._versions(project_id, params)

    def compat_any(self, project_id: str, mc_version: str, loader: Loader, *,
                   window: int = 25) -> list[VersionInfo]:
        """请求 B2：目标 MC + 目标加载器，**不过滤通道**（仅当 B 为空时发起）。"""
        params = {
            "game_versions": self._json_array([mc_version]),
            "loaders": self._json_array([loader.value]),
            "limit": str(max(1, int(window))),
        }
        return self._versions(project_id, params)

    # ---------------------------------------------------------------- 指纹反查
    def resolve_by_hash(self, sha1s: Sequence[str]) -> dict[str, VersionInfo]:
        """批量 sha1 反查（POST /version_files）。

        ⚠️ 实测：**未命中的哈希既不报错、也不出现在返回体里**，
        所以只能用"返回体里有没有这个 key"来判断，绝不能靠异常。
        """
        hashes = [str(h).lower() for h in sha1s if h]
        if not hashes:
            return {}
        cache_key = "vf_" + hashlib.sha1(",".join(sorted(hashes)).encode("utf-8")).hexdigest()
        data: Any = self.client.post_json(
            self.BASE + "/version_files",
            {"hashes": hashes, "algorithm": "sha1"},
            cache_key=cache_key)
        out: dict[str, VersionInfo] = {}
        if not isinstance(data, dict):
            return out
        for digest in hashes:
            raw = data.get(digest)
            if isinstance(raw, dict):
                out[digest] = VersionInfo.from_api(raw)
        return out


__all__ = ["ModrinthProvider"]
