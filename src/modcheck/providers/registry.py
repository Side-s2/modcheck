"""数据源注册表：按设置决定实际参与的数据源（基线 §9.4）。

界面规则：未启用的数据源显示「未启用（缺少 API Key）」，
**不得报错、不得计入红色**。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from modcheck.core.models import Settings
from modcheck.errors import ProviderUnavailable
from modcheck.i18n import t
from modcheck.providers.base import BaseProvider
from modcheck.providers.curseforge import CurseForgeProvider
from modcheck.providers.http import HttpClient
from modcheck.providers.modrinth import ModrinthProvider


@dataclass(slots=True)
class ProviderRegistry:
    """当前会话可用的数据源集合。"""

    providers: list[BaseProvider] = field(default_factory=list)

    def enabled(self) -> list[BaseProvider]:
        """可用（已配置）的数据源。"""
        return [provider for provider in self.providers if provider.available]

    def disabled(self) -> list[BaseProvider]:
        """存在但未启用的数据源。"""
        return [provider for provider in self.providers if not provider.available]

    def primary(self) -> BaseProvider:
        """主数据源；一个可用的都没有时抛 ProviderUnavailable（退出码 4）。"""
        for provider in self.enabled():
            return provider
        raise ProviderUnavailable(t("err.source.none"), code="NO_SOURCE")

    def by_name(self, name: str) -> BaseProvider | None:
        """按机器名取数据源。"""
        for provider in self.providers:
            if provider.name == name:
                return provider
        return None

    def status_line(self) -> tuple[str, str]:
        """返回 (Modrinth 状态文案, CurseForge 状态文案)，供横幅与报告头使用。"""
        modrinth = "source.modrinth.enabled"
        curseforge = "source.curseforge.disabled"
        provider = self.by_name("modrinth")
        if provider is None or not provider.available:
            modrinth = "source.modrinth.disabled"
        cf = self.by_name("curseforge")
        if cf is not None and cf.available:
            curseforge = "source.curseforge.enabled"
        return t(modrinth), t(curseforge)

    @classmethod
    def from_settings(cls, settings: Settings, client: HttpClient) -> "ProviderRegistry":
        """按 settings.providers.* 组装数据源。"""
        conf = settings.providers or {}
        providers: list[BaseProvider] = []
        modrinth_conf = conf.get("modrinth") or {}
        if modrinth_conf.get("enabled", True):
            providers.append(ModrinthProvider(client))
        cf_conf = conf.get("curseforge") or {}
        if cf_conf.get("enabled"):
            # 真正实现之后，这里会带上 api_key；当前 CurseForgeProvider.available 恒为 False
            providers.append(CurseForgeProvider(cf_conf.get("api_key")))
        else:
            providers.append(CurseForgeProvider(None))
        return cls(providers=providers)


__all__ = ["ProviderRegistry"]
