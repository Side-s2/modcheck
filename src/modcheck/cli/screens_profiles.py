"""菜单 [3]：管理模组清单的交互屏（PRD §13.2，R3-A03 ~ R3-A10）。

分层：屏幕与编排只在这里；所有业务规则在 core/profile_ops.py，写盘在 storage/profiles.py。
三条硬约束（R3 任务书 §0）：Prompter 可注入；非 TTY 不提问（prompts.Prompter 已兜住）；
只有打包产物才调 pause_before_exit（本模块不调）。
"""
from __future__ import annotations

from typing import Callable, Final

from modcheck.cli.context import AppContext
from modcheck.cli.prompts import (KIND_BACK, KIND_OK, KIND_QUIT, MAX_INVALID_TRIES, Prompter,
                                  read_line)
from modcheck.core.profile_ops import INVALID_NAME_CHARS, validate_profile_name
from modcheck.errors import ConfigError, ModcheckError
from modcheck.i18n import t
from modcheck.storage.profiles import (ProfileSummary, list_profiles, load_profile,
                                       new_profile, profile_path, save_profile)

#: 屏幕返回值
QUIT: Final[str] = KIND_QUIT
BACK: Final[str] = KIND_BACK
OPEN: Final[str] = "open"
NEW: Final[str] = "new"

#: 管理屏的操作表：(按键, 文案 key, 处理函数名)
#: 逐条长出来（R3-A04 查看 / A05 删除 / A06 指定 / A07 忽略 / A08 重命名 / A09 删除清单），
#: 最终顺序与 PRD §13.2 完全一致。
MANAGE_ITEMS: Final[tuple[tuple[str, str], ...]] = ()


def run_profiles_screen(ctx: AppContext) -> str:
    """菜单 [3] 的入口：清单列表屏循环。返回 quit 表示回主菜单。"""
    while True:
        summaries = list_profiles(ctx.profiles_dir)
        action, value = _list_screen(ctx, ctx.prompter, summaries)
        if action == QUIT:
            return QUIT
        if action == OPEN and _manage_screen(ctx, ctx.prompter, value) == QUIT:
            return QUIT
        if action == NEW:
            _new_profile(ctx, ctx.prompter)


def summary_line(summary: ProfileSummary, index: int) -> str:
    """清单列表里的一行（用户要求带上修改日期；损坏的清单只显示错误）。"""
    if summary.error:
        return t("manage.item.broken", index=index, name=summary.name, error=summary.error)
    stamp = (summary.updated_at or "").strip()
    short = stamp[:16].replace("T", " ")          # 2026-10-01T21:40:31 -> 2026-10-01 21:40
    if len(short) == 16:
        return t("manage.item", index=index, name=summary.name,
                 count=summary.mod_count, date=short)
    return t("manage.item.nodate", index=index, name=summary.name, count=summary.mod_count)


def print_list_screen(ctx: AppContext, summaries: list[ProfileSummary]) -> None:
    """清单列表屏（PRD §13.2 逐字）。"""
    console = ctx.console
    console.line(t("manage.title"))
    console.line(t("manage.config_dir", path=ctx.profiles_dir))
    console.line()
    if summaries:
        for index, summary in enumerate(summaries, start=1):
            console.line(summary_line(summary, index))
    else:
        console.line(t("manage.empty"))
    console.line()
    if summaries:
        console.line(t("manage.hint.open"))
    console.line(t("manage.hint.new"))
    console.line(t("manage.hint.quit"))


def _list_screen(ctx: AppContext, prompter: Prompter,
                 summaries: list[ProfileSummary]) -> tuple[str, str]:
    """列表屏循环；返回 (OPEN, 清单名) / (NEW, "") / (QUIT, "")。"""
    console = ctx.console
    while True:                                   # 重新画屏（[m] 输错后要回到这里）
        print_list_screen(ctx, summaries)
        if len(summaries) > 9:
            console.line(t("manage.hint.by_name"))
        tries = 0
        while True:
            kind, value = read_line(prompter, t("menu.prompt"))
            if kind in (QUIT, BACK):
                return QUIT, ""
            if kind == KIND_OK and value:
                picked = _match_summary(summaries, value)
                if picked is not None:
                    return OPEN, picked
                if value.lower() == "n":
                    return NEW, ""
                if value.lower() == "m" and summaries:
                    chosen = _ask_profile_name(ctx, prompter, summaries)
                    if chosen is not None:
                        return OPEN, chosen
                    break                          # 重画列表屏
            tries += 1
            console.line(t("menu.invalid_choice"))
            if tries >= MAX_INVALID_TRIES:
                console.line(t("screen.too_many_invalid"))
                return QUIT, ""


def _match_summary(summaries: list[ProfileSummary], value: str) -> str | None:
    """按编号或完整名称找清单；找不到返回 None。"""
    text = value.strip()
    if text.isdigit():
        index = int(text)
        if 1 <= index <= len(summaries):
            return summaries[index - 1].name
        return None
    wanted = text.lower()
    for summary in summaries:
        if summary.name.lower() == wanted:
            return summary.name
    return None


def _ask_profile_name(ctx: AppContext, prompter: Prompter,
                      summaries: list[ProfileSummary]) -> str | None:
    """[m] 手输清单名；不存在时打印可用清单（PRD §13.4 第 5 条）。"""
    kind, value = read_line(prompter, t("manage.by_name.prompt"))
    if kind != KIND_OK or not value:
        return None
    picked = _match_summary(summaries, value)
    if picked is not None:
        return picked
    available = "、".join(item.name for item in summaries) or t("err.profile.none_available")
    ctx.console.line(t("manage.not_found", name=value, available=available))
    return None


def _load_profile(ctx: AppContext, name: str):
    """读清单；读不了时打印原因并返回 None（损坏的清单不该让屏幕崩掉）。"""
    try:
        return load_profile(profile_path(ctx.profiles_dir, name))
    except ModcheckError as exc:
        ctx.console.line(exc.message)
        return None


def _manage_screen(ctx: AppContext, prompter: Prompter, name: str) -> str:
    """单个清单的管理屏（PRD §13.2）；返回 QUIT 或 BACK。"""
    console = ctx.console
    tries = 0
    while True:
        profile = _load_profile(ctx, name)
        if profile is None:
            return BACK
        console.line(t("manage.one.title", name=profile.name, count=len(profile.mods)))
        for key, label_key in MANAGE_ITEMS:
            console.line(t(label_key))
        console.line(t("manage.one.back"))
        console.line(t("manage.one.quit"))
        kind, value = read_line(prompter, t("menu.prompt"))
        if kind == QUIT:
            return QUIT
        if kind == BACK or value.lower() == "b":
            return BACK
        handler = MANAGE_HANDLERS.get(value.lower())
        if handler is None:
            tries += 1
            console.line(t("menu.invalid_choice"))
            if tries >= MAX_INVALID_TRIES:
                console.line(t("screen.too_many_invalid"))
                return BACK
            continue
        tries = 0
        handler(ctx, prompter, name)


#: 按键 -> 处理函数（R3-A04~A09 逐条填进来）
MANAGE_HANDLERS: dict[str, Callable[[AppContext, Prompter, str], None]] = {}


def _new_profile(ctx: AppContext, prompter: Prompter) -> None:
    """新建空清单（R3-A10）。"""
    console = ctx.console
    tries = 0
    while True:
        kind, value = read_line(prompter, t("manage.new.prompt"))
        if kind != KIND_OK:
            return
        try:
            validate_profile_name(value)
        except ConfigError as exc:
            console.line(exc.message)
            tries += 1
            if tries >= MAX_INVALID_TRIES:
                console.line(t("screen.too_many_invalid"))
                return
            continue
        path = profile_path(ctx.profiles_dir, value)
        if path.exists():
            console.line(t("manage.new.exists", name=value.strip()))
            tries += 1
            if tries >= MAX_INVALID_TRIES:
                console.line(t("screen.too_many_invalid"))
                return
            continue
        try:
            save_profile(new_profile(value), path)
        except (ModcheckError, OSError):
            console.line(t("manage.new.failed", path=path))
            return
        console.line(t("manage.new.done", name=value.strip()))
        return


def invalid_chars_text() -> str:
    """非法字符的展示文本（只此一份，避免文案与校验规则走样）。"""
    return " ".join(INVALID_NAME_CHARS)


__all__ = ["run_profiles_screen", "MANAGE_ITEMS", "MANAGE_HANDLERS", "print_list_screen",
           "summary_line", "invalid_chars_text", "QUIT", "BACK", "OPEN", "NEW"]
