"""数据源抽象基类（Provider 契约，基线 §9.1）。

core 只依赖这个抽象：它通过注入的 Provider 取数据，绝不 import 具体实现。
子类**只需要实现 3 个方法**（search / get_project / get_versions），
下面 4 个方法有基于 get_versions 的默认实现（顺序原样保留，绝不重排）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from modcheck.core.models import Loader, ProjectHit, ProjectInfo, VersionInfo


class BaseProvider(ABC):
    """数据源基类。"""

    #: 机器名（modrinth / curseforge）
    name: str = ""
    #: 界面显示名
    display_name: str = ""
    #: 是否已配置可用（CurseForge 无 Key 时恒为 False）
    available: bool = True

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[ProjectHit]:
        """按名字搜索项目。"""

    @abstractmethod
    def get_project(self, project_id: str) -> ProjectInfo | None:
        """取项目详情；项目不存在返回 None。"""

    @abstractmethod
    def get_versions(self, project_id: str) -> list[VersionInfo]:
        """取版本列表（**顺序即 API 返回顺序，禁止重排**）。"""

    # ---------------------------------------------------------------- 必须自己实现
    #
    # ⚠️ 这三个方法**故意不给默认实现**。
    # 曾经写成"基于 get_versions() 本地过滤"，但那就是"全量拉取"——
    # 实测 JEI 单模组 3736 条 / 6.8 MB，200 个模组外推约 326 MB（基线 §9.5.1）。
    # 默认实现能跑通、单测全绿，直到拿真实数据才发现又慢又会被限流，
    # 属于典型的"继承就能用、用了就错"。两个计划中的数据源（Modrinth / CurseForge）
    # 都支持服务端过滤，所以强制每个数据源自己实现带过滤条件的查询。
    @abstractmethod
    def releases_for_loader(self, project_id: str, loader: Loader, *, window: int = 25,
                            prerelease: bool = False) -> list[VersionInfo]:
        """请求 A：目标加载器的最新版本（必须服务端过滤 + limit）。"""

    @abstractmethod
    def compat_releases(self, project_id: str, mc_version: str, loader: Loader, *,
                        window: int = 25, prerelease: bool = False) -> list[VersionInfo]:
        """请求 B：目标加载器 + 目标 MC 版本的版本（必须服务端过滤 + limit）。"""

    @abstractmethod
    def any_for_loader(self, project_id: str, loader: Loader, *, window: int = 25) -> list[VersionInfo]:
        """请求 A2：只按加载器过滤（不过滤通道），用于判断"只有测试版"。"""

    def resolve_by_hash(self, sha1s: Sequence[str]) -> dict[str, VersionInfo]:
        """用文件指纹反查版本；不支持的数据源返回空字典。"""
        return {}


def filter_versions(versions: Sequence[VersionInfo], *, loader: Loader,
                    mc_version: str | None, prerelease: bool,
                    window: int) -> list[VersionInfo]:
    """按加载器 / MC 版本 / 通道过滤，保持原顺序并截断到 window 条。

    **仅供内存假 Provider 与确实不支持服务端过滤的数据源使用**；
    真实网络数据源（Modrinth / CurseForge）必须走带过滤参数的端点，
    否则会退化成全量拉取（基线 §9.5.1 实测禁止）。
    """
    out: list[VersionInfo] = []
    for version in versions:
        if loader.value not in version.loaders:
            continue
        if mc_version is not None and mc_version not in version.game_versions:
            continue
        if not prerelease and not version.is_release:
            continue
        out.append(version)
        if len(out) >= window:
            break
    return out


__all__ = ["BaseProvider", "filter_versions"]
