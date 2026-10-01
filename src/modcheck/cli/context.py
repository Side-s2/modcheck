"""应用上下文：把设置、数据源、缓存、控制台装配成 CLI 各命令的依赖包。

依赖注入的边界在这里：core 与 providers 都只拿到接口对象，
CLI 负责把具体实现拼起来（这样 GUI 也能复用同一套装配逻辑）。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from modcheck.cache import HttpCache
from modcheck.console import Console
from modcheck.core.models import Loader, Settings
from modcheck.errors import ProviderError
from modcheck.flows.runtime import MAX_JOBS, RATE_LIMIT_PER_MIN, build_runtime
from modcheck.i18n import t
from modcheck.providers.http import HttpClient
from modcheck.providers.registry import ProviderRegistry
from modcheck.storage import paths as path_helpers


@dataclass(slots=True)
class AppContext:
    """一次命令行调用的全部依赖。"""

    settings: Settings
    config_dir: Path
    console: Console
    registry: ProviderRegistry
    cache: HttpCache | None
    client: HttpClient
    prompter: Any = None
    interactive: bool = False
    debug: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def profiles_dir(self) -> Path:
        """清单目录。"""
        return path_helpers.profiles_dir(self.config_dir)

    @property
    def settings_path(self) -> Path:
        """设置文件路径。"""
        return path_helpers.settings_path(self.config_dir)


def build_context(args: Any, console: Console) -> AppContext:
    """按命令行参数与设置装配上下文。

    ⚠️ 真正的装配**已经下沉到 flows/runtime.py**，与 GUI 共用同一份实现 ——
    之前这段逻辑住在这里，GUI 因为拿不到 argparse/Console 而无法复用，
    两边各写一份迟早会漂移（代理/超时/限速/缓存都是全局行为，差一点就会"只在一边复现"）。
    这里只保留 CLI 特有的部分：Console 的颜色开关、交互判定与 Prompter。
    """
    debug = bool(getattr(args, "debug", False))
    runtime = build_runtime(config_dir=getattr(args, "config_dir", None),
                            jobs=getattr(args, "jobs", None),
                            refresh=bool(getattr(args, "refresh", False)),
                            debug=debug)
    warnings: list[str] = list(runtime.warnings)
    config_dir, settings = runtime.config_dir, runtime.settings
    if settings.color == "never":
        console.color_enabled = False

    cache, client, registry = runtime.cache, runtime.client, runtime.registry
    interactive = sys.stdin.isatty() and not bool(getattr(args, "yes", False))

    prompter = None
    if interactive:
        from modcheck.cli.prompts import Prompter

        prompter = Prompter(out=console)

    ctx = AppContext(settings=settings, config_dir=config_dir, console=console,
                     registry=registry, cache=cache, client=client, prompter=prompter,
                     interactive=interactive, debug=debug, warnings=warnings)
    for warning in warnings:
        console.line(warning)
    return ctx


def loader_from_args(args: Any, ctx: AppContext) -> Loader:
    """从参数或设置里取目标加载器。"""
    raw = getattr(args, "loader", None)
    if raw:
        return Loader.parse(raw)
    return ctx.settings.default_loader


def provider_or_none(ctx: AppContext) -> Any:
    """可用的主数据源；一个都没有时返回 None。

    与 registry.primary()（抛 ProviderUnavailable -> 退出码 4）的区别在于调用方的意图：
    扫描允许"没有数据源"，只是识别率低一点；检查则必须报错退出。
    """
    try:
        return ctx.registry.primary()
    except ProviderError:
        return None


__all__ = ["AppContext", "build_context", "loader_from_args", "provider_or_none",
           "MAX_JOBS", "RATE_LIMIT_PER_MIN"]
