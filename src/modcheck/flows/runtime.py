"""运行时装配：把设置、缓存、限速器、数据源拼成一套**可复用**的依赖。

为什么单独抽出来
----------------
这段逻辑原本写在 cli/context.py 里，入口是 build_context(args, console) ——
它依赖 argparse 的 Namespace 和 Console，**GUI 其实复用不了**（尽管那里的注释写着"GUI 也能复用"）。

抽到这里之后 CLI 与 GUI 才真正共用同一套装配。这不只是省几行代码：
装配决定了代理、超时、重试、限速、缓存这些**全局行为**，
两边各写一份迟早会漂移，届时会出现"同一个设置在 GUI 里没生效"这种只在一边复现的怪问题。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from modcheck.cache import HttpCache
from modcheck.core.models import Settings
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
class Runtime:
    """一次会话的全部依赖（不含任何展示层对象）。"""

    config_dir: Path
    settings: Settings
    registry: ProviderRegistry
    client: HttpClient
    cache: HttpCache | None
    warnings: list[str] = field(default_factory=list)

    @property
    def profiles_dir(self) -> Path:
        """清单目录。"""
        return path_helpers.profiles_dir(self.config_dir)

    @property
    def settings_path(self) -> Path:
        """设置文件路径。"""
        return path_helpers.settings_path(self.config_dir)


def build_runtime(*, config_dir: str | Path | None = None, jobs: int | None = None,
                  refresh: bool = False, debug: bool = False) -> Runtime:
    """装配运行时。

    参数与 CLI 的解耦方式：CLI 把自己的 argparse 值传进来，GUI 直接传自己的值 ——
    这个函数不认识 argparse，也不认识 Console。
    """
    warnings: list[str] = []
    requested = path_helpers.resolve_config_dir(
        str(config_dir) if config_dir else None, exe_dir=path_helpers.detect_exe_dir())
    resolved, fell_back = path_helpers.ensure_config_dir(requested)
    if fell_back:
        warnings.append(t("err.config_dir.not_writable", old=requested, new=resolved))

    settings = load_settings(path_helpers.settings_path(resolved))

    if jobs is not None:
        if jobs > MAX_JOBS:
            if debug:
                warnings.append(t("err.debug.jobs_clamped", high=MAX_JOBS))
            jobs = MAX_JOBS
        settings.concurrency = max(1, min(int(jobs), MAX_JOBS))

    cache: HttpCache | None = HttpCache(path_helpers.http_cache_dir(resolved))
    if not path_helpers.is_writable(path_helpers.http_cache_dir(resolved)):
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
    if refresh:
        client.use_cache = False

    registry = ProviderRegistry.from_settings(settings, client)
    return Runtime(config_dir=resolved, settings=settings, registry=registry,
                   client=client, cache=cache, warnings=warnings)


__all__ = ["Runtime", "build_runtime", "MAX_JOBS", "RATE_LIMIT_PER_MIN"]
