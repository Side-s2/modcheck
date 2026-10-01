"""versions / config / cache 三个小命令。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from modcheck.cli.context import AppContext
from modcheck.core.mcversion import sort_releases
from modcheck.errors import ConfigError, ProviderError
from modcheck.i18n import t
from modcheck.providers.mojang import MojangVersions
from modcheck.storage import paths as path_helpers
from modcheck.storage.settings import SETTING_KEYS, save_settings, set_setting

__all__ = ["run_versions", "run_config", "run_cache"]


def run_versions(args: argparse.Namespace, ctx: AppContext) -> int:
    """查看官方正式版列表（只取 release）。"""
    limit = int(getattr(args, "limit", 10) or 10)
    try:
        versions = MojangVersions(ctx.client)
        releases = versions.list_releases(limit=limit)
    except ProviderError as exc:
        if getattr(args, "json_out", False):
            ctx.console.line(json.dumps([], ensure_ascii=False))
        ctx.console.line(exc.message)
        ctx.console.line(t("versions.offline"))
        return 2
    if getattr(args, "json_out", False):
        ctx.console.line(json.dumps([{"version": item.version_id, "release_time": item.release_time}
                                     for item in releases], ensure_ascii=False, indent=2))
        return 0
    hours = int(ctx.settings.cache_ttl_hours.get("mojang", 24))
    ctx.console.line(t("versions.header", hours=hours))
    ctx.console.line()
    for index, item in enumerate(releases, start=1):
        ctx.console.line(t("versions.item", index=index, version=item.version_id,
                           date=item.release_time[:10]))
    ctx.console.line()
    ctx.console.line(t("versions.hint"))
    return 0


def run_config(args: argparse.Namespace, ctx: AppContext) -> int:
    """读 / 写设置。"""
    action = (getattr(args, "action", None) or "show").lower()
    if action == "path":
        ctx.console.line(t("config.path_line", path=ctx.settings_path))
        return 0
    if action == "reset":
        save_settings(ctx.settings_path, type(ctx.settings)())
        ctx.console.line(t("config.reset_done", path=ctx.settings_path))
        return 0
    if action == "set":
        key = getattr(args, "key", None)
        value = getattr(args, "value", None)
        if not key or value is None:
            raise ConfigError(t("config.unknown_key", key=str(key), keys="、".join(SETTING_KEYS)))
        set_setting(ctx.settings, str(key), str(value))
        save_settings(ctx.settings_path, ctx.settings)
        ctx.console.line(t("config.saved", key=key, value=value))
        return 0
    if action != "show":
        raise ConfigError(t("config.unknown_key", key=action, keys="show、set、path、reset"))
    settings = ctx.settings
    modrinth, curseforge = ctx.registry.status_line()
    ctx.console.line(t("config.show.header", path=ctx.settings_path))
    ctx.console.line()
    ctx.console.line(t("config.show.item", label=t("config.label.default_mc"),
                       value=settings.default_mc_version or t("config.value.not_set")))
    ctx.console.line(t("config.show.item", label=t("config.label.default_loader"),
                       value=settings.default_loader.value))
    ctx.console.line(t("config.show.item", label=t("config.label.color"), value=settings.color))
    ctx.console.line(t("config.show.item", label=t("config.label.proxy"),
                       value=settings.proxy or t("config.value.not_set")))
    ctx.console.line(t("config.show.item", label=t("config.label.concurrency"),
                       value=t("config.value.concurrency", value=settings.concurrency)))
    ctx.console.line(t("config.show.item", label=t("config.label.timeout"),
                       value=t("config.value.timeout", value=int(settings.timeout_seconds),
                               retries=settings.retries)))
    ctx.console.line(t("config.show.item", label=t("config.label.cache"),
                       value=t("config.value.cache",
                               mojang=int(settings.cache_ttl_hours.get("mojang", 24)),
                               api=int(settings.cache_ttl_hours.get("api", 6)))))
    ctx.console.line(t("config.show.item", label=t("config.label.providers"),
                       value=t("config.value.providers", modrinth=modrinth, curseforge=curseforge)))
    ctx.console.line()
    ctx.console.line(t("config.hint"))
    return 0


def run_cache(args: argparse.Namespace, ctx: AppContext) -> int:
    """缓存查看与清理。"""
    action = (getattr(args, "action", None) or "info").lower()
    root = path_helpers.http_cache_dir(ctx.config_dir)
    if action == "clear":
        older = _parse_duration(getattr(args, "older_than", None))
        removed = ctx.cache.clear(older_than=older) if ctx.cache is not None else 0
        ctx.console.line(t("cache.cleared", count=removed))
        return 0
    ctx.console.line(t("cache.info.header", dir=path_helpers.cache_dir(ctx.config_dir)))
    info = ctx.cache.info() if ctx.cache is not None else None
    if info is None or info.files == 0:
        ctx.console.line(t("cache.info.empty"))
    else:
        ctx.console.line(t("cache.info.item", files=info.files,
                           size=_human_size(info.bytes),
                           oldest=_stamp(info.oldest), newest=_stamp(info.newest)))
    ctx.console.line(t("cache.info.hint"))
    return 0


def _parse_duration(raw: str | None) -> float | None:
    """把 7d / 12h / 30m 解析成秒。"""
    if not raw:
        return None
    text = str(raw).strip().lower()
    unit = text[-1]
    number = text[:-1] if unit.isalpha() else text
    try:
        value = float(number)
    except ValueError:
        raise ConfigError(t("config.bad_value", key="--older-than", value=raw)) from None
    factor = {"d": 86400.0, "h": 3600.0, "m": 60.0, "s": 1.0}.get(unit, 1.0)
    return value * factor


def _human_size(size: int) -> str:
    """字节数转可读文本。"""
    if size >= 1024 * 1024:
        return t("size.mb", n=round(size / 1024 / 1024, 1))
    if size >= 1024:
        return t("size.kb", n=round(size / 1024, 1))
    return t("size.bytes", n=size)


def _stamp(value: float | None) -> str:
    """时间戳转 YYYY-MM-DD HH:MM。"""
    import time as _time

    if not value:
        return t("config.value.not_set")
    return _time.strftime("%Y-%m-%d %H:%M", _time.localtime(value))
