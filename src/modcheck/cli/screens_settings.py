"""菜单 [4]：设置屏（PRD §13.3，R3-A11 ~ R3-A12）。

分层：屏幕与编排只在这里；取值校验在 core/settings_ops.py，写盘在 storage/settings.py。
写盘失败的语义（主 Agent 裁决）：设置是「本次运行立即生效」，所以**保留内存里的新值**，
只打 PRD §13.3 那句 ✗ 文案；清单类操作才是「内存与磁盘都不变」。
"""
from __future__ import annotations

from typing import Callable, Final

from modcheck.cli.context import AppContext
from modcheck.cli.prompts import (KIND_BACK, KIND_OK, KIND_QUIT, MAX_INVALID_TRIES, Prompter,
                                  read_line)
from modcheck.core.models import Loader, Settings
from modcheck.core.settings_ops import (COLORS, JOBS_HIGH, JOBS_LOW, TTL_HIGH, TTL_KEYS,
                                        TTL_LOW, mask_secret, reset_settings, set_cache_ttl,
                                        set_color, set_concurrency, set_curseforge_key,
                                        set_default_loader, set_default_mc, set_proxy)
from modcheck.errors import ConfigError, ModcheckError
from modcheck.i18n import t
from modcheck.storage.settings import save_settings

QUIT: Final[str] = KIND_QUIT
BACK: Final[str] = KIND_BACK

#: 颜色模式的展示文案
COLOR_LABEL_KEYS: Final[dict[str, str]] = {
    "auto": "settings.value.color.auto",
    "always": "settings.value.color.always",
    "never": "settings.value.color.never",
}


def value_mc(settings: Settings) -> str:
    """[1] 的值：版本号或未设置。"""
    return settings.default_mc_version or t("config.value.not_set")


def value_loader(settings: Settings) -> str:
    """[2] 的值：Fabric（fabric）。"""
    return t("settings.value.loader", name=settings.default_loader.display_name,
             value=settings.default_loader.value)


def value_proxy(settings: Settings) -> str:
    """[3] 的值。"""
    return settings.proxy or t("config.value.not_set")


def value_color(settings: Settings) -> str:
    """[4] 的值。"""
    return t(COLOR_LABEL_KEYS.get(settings.color, "settings.value.color.auto"))


def value_jobs(settings: Settings) -> str:
    """[5] 的值。"""
    return str(settings.concurrency)


def value_cache(settings: Settings) -> str:
    """[6] 的值。"""
    return t("config.value.cache",
             mojang=int(settings.cache_ttl_hours.get("mojang", 24)),
             api=int(settings.cache_ttl_hours.get("api", 6)))


def value_curseforge(settings: Settings) -> str:
    """[7] 的值：只显示后 4 位。"""
    key = (settings.providers.get("curseforge") or {}).get("api_key")
    if not key:
        return t("settings.value.cf.unset")
    return t("settings.value.cf.set", mask=mask_secret(str(key)))


#: 设置屏的 8 项：(按键, 文案 key, 取值函数)
SCREEN_ITEMS: Final[tuple[tuple[str, str, Callable[[Settings], str]], ...]] = (
    ("1", "settings.item.mc", value_mc),
    ("2", "settings.item.loader", value_loader),
    ("3", "settings.item.proxy", value_proxy),
    ("4", "settings.item.color", value_color),
    ("5", "settings.item.jobs", value_jobs),
    ("6", "settings.item.cache", value_cache),
    ("7", "settings.item.cf", value_curseforge),
)


def run_settings_screen(ctx: AppContext) -> str:
    """菜单 [4] 的入口；返回 quit 表示回主菜单。"""
    console = ctx.console
    prompter = ctx.prompter
    tries = 0
    while True:
        print_settings_screen(ctx)
        kind, value = read_line(prompter, t("menu.prompt"))
        if kind == QUIT:
            return QUIT
        if kind == BACK:
            return QUIT
        handler = SETTINGS_HANDLERS.get(value.lower())
        if handler is None:
            tries += 1
            console.line(t("menu.invalid_choice"))
            if tries >= MAX_INVALID_TRIES:
                console.line(t("screen.too_many_invalid"))
                return QUIT
            continue
        tries = 0
        if handler(ctx, prompter) == QUIT:
            return QUIT


def print_settings_screen(ctx: AppContext) -> None:
    """设置主屏（PRD §13.3 逐字）。"""
    console = ctx.console
    settings = ctx.settings
    console.line(t("settings.title"))
    console.line(t("settings.config_file", path=ctx.settings_path))
    console.line()
    for key, label_key, value_of in SCREEN_ITEMS:
        del key
        console.line(t(label_key, value=value_of(settings)))
    console.line(t("settings.item.reset"))
    console.line(t("settings.hint.quit"))


def apply_settings(ctx: AppContext, settings: Settings, message_key: str,
                   **args: object) -> None:
    """采用新设置：先更新内存（本次运行立即生效），再尝试写盘。

    写盘失败只打 ✗ 文案，**不回滚内存**（裁决：设置是本次运行立即生效的语义）。
    """
    ctx.settings = settings
    ctx.console.line(t(message_key, **args))
    try:
        save_settings(ctx.settings_path, settings)
    except (ModcheckError, OSError):
        ctx.console.line(t("settings.save_failed", path=ctx.settings_path))


def _set_mc(ctx: AppContext, prompter: Prompter) -> str | None:
    """[1] 默认游戏版本（复用菜单里的版本选择屏，额外给 [c] 清除）。"""
    from argparse import Namespace

    from modcheck.cli.menu import _screen_version

    args = Namespace(mc=None)
    if not _screen_version(args, ctx, prompter, allow_clear=True):
        return None
    known = _known_releases(ctx)
    if args.mc == "":
        return _commit(ctx, set_default_mc(ctx.settings, None, known=known),
                       "settings.mc.cleared")
    try:
        updated = set_default_mc(ctx.settings, str(args.mc), known=known)
    except ConfigError as exc:
        ctx.console.line(exc.message)
        return None
    return _commit(ctx, updated, "settings.mc.done", value=updated.default_mc_version or "")


def _known_releases(ctx: AppContext) -> list[str]:
    """官方正式版清单；取不到就返回空表（此时跳过"是否存在"校验）。"""
    from modcheck.errors import ProviderError
    from modcheck.providers.mojang import MojangVersions

    try:
        return [item.version_id for item in MojangVersions(ctx.client).list_releases(limit=50)]
    except (ProviderError, AttributeError):
        return []


def _set_loader(ctx: AppContext, prompter: Prompter) -> str | None:
    """[2] 默认加载器。"""
    console = ctx.console
    loaders = (Loader.FABRIC, Loader.NEOFORGE, Loader.FORGE)
    console.line(t("settings.loader.title"))
    console.line(t("settings.loader.options"))
    tries = 0
    while True:
        kind, value = read_line(prompter, t("menu.prompt"))
        if kind == QUIT:
            return QUIT
        if kind == BACK:
            return None
        low = value.lower()
        if low in ("1", "2", "3"):
            chosen = loaders[int(low) - 1]
            return _commit(ctx, set_default_loader(ctx.settings, chosen.value),
                           "settings.loader.done", name=chosen.display_name)
        if low == "c":
            return _commit(ctx, set_default_loader(ctx.settings, None),
                           "settings.loader.cleared")
        if low == "b":
            return None
        tries += 1
        console.line(t("menu.invalid_choice"))
        if tries >= MAX_INVALID_TRIES:
            console.line(t("screen.too_many_invalid"))
            return None


def _set_proxy(ctx: AppContext, prompter: Prompter) -> str | None:
    """[3] 代理（D42：null/none/-/空串 = 清除）。"""
    console = ctx.console
    kind, value = read_line(prompter, t("settings.proxy.prompt"))
    if kind == QUIT:
        return QUIT
    if kind == BACK:
        return None
    try:
        updated = set_proxy(ctx.settings, value)
    except ConfigError:
        console.line(t("settings.proxy.bad", value=value))
        return None
    if updated.proxy is None:
        return _commit(ctx, updated, "settings.proxy.cleared")
    return _commit(ctx, updated, "settings.proxy.done", value=updated.proxy)


def _set_color(ctx: AppContext, prompter: Prompter) -> str | None:
    """[4] 颜色。"""
    console = ctx.console
    console.line(t("settings.color.title"))
    console.line(t("settings.color.item1"))
    console.line(t("settings.color.item2"))
    console.line(t("settings.color.item3"))
    tries = 0
    while True:
        kind, value = read_line(prompter, t("menu.prompt"))
        if kind == QUIT:
            return QUIT
        if kind == BACK:
            return None
        low = value.lower()
        if low in ("1", "2", "3"):
            chosen = COLORS[int(low) - 1]
            return _commit(ctx, set_color(ctx.settings, chosen), "settings.color.done",
                           value=chosen)
        if low == "b":
            return None
        tries += 1
        console.line(t("menu.invalid_choice"))
        if tries >= MAX_INVALID_TRIES:
            console.line(t("screen.too_many_invalid"))
            return None


def _set_jobs(ctx: AppContext, prompter: Prompter) -> str | None:
    """[5] 并发数（1-8，越界就地提示并重问 ≤3 次）。"""
    console = ctx.console
    tries = 0
    while True:
        kind, value = read_line(
            prompter, t("settings.jobs.prompt", value=ctx.settings.concurrency))
        if kind == QUIT:
            return QUIT
        if kind == BACK:
            return None
        try:
            updated = set_concurrency(ctx.settings, value)
        except ConfigError as exc:
            console.line(exc.message)
            tries += 1
            if tries >= MAX_INVALID_TRIES:
                console.line(t("screen.too_many_invalid"))
                return None
            continue
        return _commit(ctx, updated, "settings.jobs.done", value=updated.concurrency)


def _set_cache(ctx: AppContext, prompter: Prompter) -> str | None:
    """[6] 缓存有效期（先选哪一项，再输 1-168 小时）。"""
    console = ctx.console
    ttl = ctx.settings.cache_ttl_hours
    console.line(t("settings.cache.title"))
    console.line(t("settings.cache.item1", hours=int(ttl.get(TTL_KEYS[0], 24))))
    console.line(t("settings.cache.item2", hours=int(ttl.get(TTL_KEYS[1], 6))))
    tries = 0
    key = ""
    while True:
        kind, value = read_line(prompter, t("menu.prompt"))
        if kind == QUIT:
            return QUIT
        if kind == BACK:
            return None
        low = value.lower()
        if low in ("1", "2"):
            key = TTL_KEYS[int(low) - 1]
            break
        if low == "b":
            return None
        tries += 1
        console.line(t("menu.invalid_choice"))
        if tries >= MAX_INVALID_TRIES:
            console.line(t("screen.too_many_invalid"))
            return None
    while True:
        kind, value = read_line(prompter, t("settings.cache.prompt"))
        if kind == QUIT:
            return QUIT
        if kind == BACK:
            return None
        try:
            updated = set_cache_ttl(ctx.settings, key, value)
        except ConfigError as exc:
            console.line(exc.message)
            tries += 1
            if tries >= MAX_INVALID_TRIES:
                console.line(t("screen.too_many_invalid"))
                return None
            continue
        hours = int(updated.cache_ttl_hours[key])
        return _commit(ctx, updated, "settings.cache.done", hours=hours)


def _set_curseforge(ctx: AppContext, prompter: Prompter) -> str | None:
    """[7] CurseForge API Key（回显只显示后 4 位）。"""
    console = ctx.console
    kind, value = read_line(prompter, t("settings.cf.prompt"))
    if kind == QUIT:
        return QUIT
    if kind == BACK:
        return None
    updated = set_curseforge_key(ctx.settings, value)
    key = (updated.providers.get("curseforge") or {}).get("api_key")
    if not key:
        return _commit(ctx, updated, "settings.cf.cleared")
    return _commit(ctx, updated, "settings.cf.done", mask=mask_secret(str(key)))


def _commit(ctx: AppContext, settings: Settings, message_key: str, **args: object) -> None:
    """统一收尾：采用新设置 + 打回执 + 尝试写盘。"""
    apply_settings(ctx, settings, message_key, **args)
    return None


def _reset(ctx: AppContext, prompter: Prompter) -> str | None:
    """[8] 重置为默认设置（二次确认，默认 N；PRD §13.3 / R3-A12）。"""
    console = ctx.console
    console.line(t("settings.reset.warn1"))
    console.line(t("settings.reset.warn2"))
    console.line(t("settings.reset.warn3"))
    console.line()
    # 危险操作：默认必须是 No（PRD §13.4 第 2 条）
    if not prompter.confirm(t("settings.reset.ask"), default=False):
        return None
    apply_settings(ctx, reset_settings(), "settings.reset.done")
    return None


#: 按键 -> 处理函数（R3-A11 的 7 个子项 + R3-A12 的重置）
SETTINGS_HANDLERS: dict[str, Callable[[AppContext, Prompter], "str | None"]] = {
    "1": _set_mc,
    "2": _set_loader,
    "3": _set_proxy,
    "4": _set_color,
    "5": _set_jobs,
    "6": _set_cache,
    "7": _set_curseforge,
    "8": _reset,
}


__all__ = ["run_settings_screen", "print_settings_screen", "apply_settings",
           "SETTINGS_HANDLERS", "SCREEN_ITEMS", "value_mc", "value_loader", "value_proxy",
           "value_color", "value_jobs", "value_cache", "value_curseforge",
           "QUIT", "BACK"]
