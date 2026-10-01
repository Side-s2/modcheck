"""【占位】CurseForge 数据源 —— 本期**不实现**，且不得发起任何网络调用。

决策 A1：用户暂时拿不到 CurseForge 的 API Key，所以本期只留扩展位。
本模块的存在意义是把"以后怎么补"写清楚，避免下一轮重新调研。

===============================================================================
未来补全所需的一切（对照基线 §9.4 与 PRD §8 第 1 条）
===============================================================================
1) 认证
   * 请求头 x-api-key: <KEY>（CurseForge 的 v1 API 全靠这个头，没有 OAuth）。
   * Key 来源优先级：
       ① settings.providers.curseforge.api_key（settings.json）
       ② 环境变量 CURSEFORGE_API_KEY
       ③ 都没有 -> available = False，界面上显示"未启用（缺少 API Key）"，不报错。

2) 端点（https://api.curseforge.com/v1）
   * GET  /v1/mods/search?gameId=432&classId=6&searchFilter=<名字>&pageSize=10
        gameId=432 是 Minecraft；classId=6 是 Mods（不是整合包/材质）。
   * GET  /v1/mods/{modId}
   * GET  /v1/mods/{modId}/files?gameVersion=<MC>&modLoaderType=<n>&pageSize=25
   * POST /v1/mods/fingerprints           body {"fingerprints": [<murmur2>, ...]}
        批量反查本地 jar，等价于 Modrinth 的 /version_files。
   * 分页用 index + pageSize（上限 50）。

3) modLoaderType 枚举
   1 = Forge ｜ 4 = Fabric ｜ 6 = NeoForge
   （映射到本项目的 Loader 时注意：Forge=1、Fabric=4、NeoForge=6。）

4) 文件指纹算法：**MurmurHash2**（32 位，seed = 1），
   而不是 Modrinth 用的 sha1。计算前必须先剔除 jar 里的签名相关条目
   （META-INF/*.SF、*.RSA、*.DSA、MANIFEST.MF 的摘要），否则指纹对不上。
   标准库没有 murmur2，需要自己实现（约 30 行，无第三方依赖）。

5) 版本通道：CurseForge 的 releaseType 1=release / 2=beta / 3=alpha，
   与本项目的 release|beta|alpha 一一对应。

6) 在 registry.py 中启用它的方法：
       settings.providers.curseforge = {"enabled": true, "api_key": "<KEY>"}
   然后 ProviderRegistry.from_settings() 会自动把它放进 enabled() 列表；
   core 层不需要任何改动（这正是留扩展位的意义）。

7) 限流：CurseForge 没有公开的速率头，建议保守使用 100 次/分钟，
   并复用 providers/http.py 的 RateLimiter。

===============================================================================
"""
from __future__ import annotations

from typing import Sequence

from modcheck.core.models import Loader, ProjectHit, ProjectInfo, VersionInfo
from modcheck.errors import ProviderUnavailable
from modcheck.i18n import t
from modcheck.providers.base import BaseProvider


class CurseForgeProvider(BaseProvider):
    """CurseForge 占位实现：可用性恒为 False，任何调用都抛领域异常。"""

    name = "curseforge"
    display_name = "CurseForge"
    available = False

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    def _unavailable(self) -> ProviderUnavailable:
        """统一的不可用异常（文案走 i18n）。"""
        return ProviderUnavailable(t("err.cf.no_key"), code="CF_NO_KEY")

    def search(self, query: str, limit: int = 10) -> list[ProjectHit]:
        """占位：未启用。"""
        raise self._unavailable()

    def get_project(self, project_id: str) -> ProjectInfo | None:
        """占位：未启用。"""
        raise self._unavailable()

    def get_versions(self, project_id: str) -> list[VersionInfo]:
        """占位：未启用。"""
        raise self._unavailable()

    def releases_for_loader(self, project_id: str, loader: Loader, *, window: int = 25,
                            prerelease: bool = False) -> list[VersionInfo]:
        """占位：未启用。"""
        raise self._unavailable()

    def compat_releases(self, project_id: str, mc_version: str, loader: Loader, *,
                        window: int = 25, prerelease: bool = False) -> list[VersionInfo]:
        """占位：未启用。"""
        raise self._unavailable()

    def any_for_loader(self, project_id: str, loader: Loader, *, window: int = 25) -> list[VersionInfo]:
        """占位：未启用。"""
        raise self._unavailable()

    def resolve_by_hash(self, sha1s: Sequence[str]) -> dict[str, VersionInfo]:
        """占位：未启用。"""
        raise self._unavailable()


__all__ = ["CurseForgeProvider"]
