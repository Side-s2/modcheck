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
from modcheck.i18n import t
from modcheck.providers.http import HttpConfig, HttpClient, RateLimiter
from modcheck.providers.registry import ProviderRegistry
from modcheck.storage import paths as path_helpers
from modcheck.storage.settings import load_settings

#: 并发硬上限（PRD §12：默认 6，上限 8）
MAX_JOBS = 8
#: Modrinth 官方 300 req/min；留 20% 余量取 240，
#: 这样"任意 60 秒滑动窗口 <= 240"成立（PM 的 R2-02 验收口径）
RATE_LIMIT_PER_MIN = 240


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
    """按命令行参数与设置装配上下文。"""
    warnings: list[str] = []
    debug = bool(getattr(args, "debug", False))
    requested = path_helpers.resolve_config_dir(getattr(args, "config_dir", None),
                                                exe_dir=path_helpers.detect_exe_dir())
    config_dir, fell_back = path_helpers.ensure_config_dir(requested)
    if fell_back:
        warnings.append(t("err.config_dir.not_writable", old=requested, new=config_dir))

    settings = load_settings(path_helpers.settings_path(config_dir))
    if settings.color == "never":
        console.color_enabled = False

    jobs = getattr(args, "jobs", None)
    if jobs is not None:
        if jobs > MAX_JOBS:
            if debug:
                warnings.append(t("err.debug.jobs_clamped", high=MAX_JOBS))
            jobs = MAX_JOBS
        settings.concurrency = max(1, min(int(jobs), MAX_JOBS))

    cache: HttpCache | None = HttpCache(path_helpers.http_cache_dir(config_dir))
    if not path_helpers.is_writable(path_helpers.http_cache_dir(config_dir)):
        cache = None
        warnings.append(t("warn.cache.not_writable"))

    cfg = HttpConfig(
        timeout=float(settings.timeout_seconds),
        retries=int(settings.retries),
        proxy=settings.proxy,
        rate_limit_per_min=RATE_LIMIT_PER_MIN,
        cache_ttl=float(settings.cache_ttl_hours.get("api", 6.0)) * 3600.0,
    )
    client = HttpClient(cfg, cache=cache, limiter=RateLimiter(cfg.rate_limit_per_min))
    if getattr(args, "refresh", False):
        client.use_cache = False

    registry = ProviderRegistry.from_settings(settings, client)
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


__all__ = ["AppContext", "build_context", "loader_from_args", "MAX_JOBS", "RATE_LIMIT_PER_MIN"]
