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
from modcheck.cli.render import assemble_row
from modcheck.console import display_width
from modcheck.core.models import ModEntry
from modcheck.core.profile_ops import (INVALID_NAME_CHARS, PAGE_SIZE, display_name_of,
                                       page_of, parse_project_selector, remove_mods, rename,
                                       resolve_selector, set_ignored, set_source,
                                       validate_profile_name)
from modcheck.errors import ConfigError, ModcheckError, ProviderError
from modcheck.i18n import t
from modcheck.storage.profiles import (ProfileSummary, delete_profile, list_profiles,
                                       load_profile, new_profile, profile_path, save_profile)

#: 屏幕返回值
QUIT: Final[str] = KIND_QUIT
BACK: Final[str] = KIND_BACK
OPEN: Final[str] = "open"
NEW: Final[str] = "new"

#: 管理屏的操作表：(按键, 文案 key, 处理函数名)
#: 逐条长出来（R3-A04 查看 / A05 删除 / A06 指定 / A07 忽略 / A08 重命名 / A09 删除清单），
#: 最终顺序与 PRD §13.2 完全一致。
MANAGE_ITEMS: Final[tuple[tuple[str, str], ...]] = (
    ("1", "manage.one.view"),
    ("2", "manage.one.remove"),
    ("3", "manage.one.set_source"),
    ("4", "manage.one.ignore"),
    ("r", "manage.one.rename"),
    ("d", "manage.one.delete"),
)

#: 匹配状态列的文字（PRD §13.2 的「匹配」列）
MATCH_STATUS_KEYS: Final[dict[str, str]] = {
    "exact": "match.status.exact",
    "manual": "match.status.manual",
    "unmatched": "match.status.unmatched",
    "ignored": "match.status.ignored",
    "guess": "match.status.guess",
}


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
        result = handler(ctx, prompter, name)
        if result == QUIT:
            return QUIT
        if result and result != BACK:
            # 操作换了清单名（重命名）：后续屏要用新名字，否则会"清单读不了"
            name = result


def match_cell(entry: ModEntry) -> str:
    """「匹配」列的文字。"""
    return t(MATCH_STATUS_KEYS.get(entry.match_status.value, "match.status.unmatched"))


def _table_rows(entries: list[ModEntry], *, offset: int) -> list[tuple[str, ...]]:
    """模组列表的行（列与 profile show 一致，第五列改成「匹配」）。"""
    return [(str(offset + index), display_name_of(entry), entry.mod_id or entry.key,
             str(entry.sources.get("modrinth") or t("report.item.empty_cell")),
             match_cell(entry),
             entry.current_version or t("report.item.empty_cell"))
            for index, entry in enumerate(entries, start=1)]


def _print_table(console, rows: list[tuple[str, ...]]) -> None:
    """打印表头 + 数据行（表头与数据行必须用同一套列宽，D32）。"""
    headers = (t("profile.show.col.index"), t("profile.show.col.name"),
               t("profile.show.col.modid"), t("profile.show.col.source"),
               t("manage.view.col.match"), t("profile.show.col.version"))
    widths = [max(display_width(headers[i]), *(display_width(row[i]) for row in rows))
              for i in range(len(headers))]
    widths[0] = max(widths[0], 3)
    console.line(assemble_row(headers, widths))
    for row in rows:
        console.line(assemble_row(row, widths))


def _op_view(ctx: AppContext, prompter: Prompter, name: str) -> str | None:
    """[1] 查看模组列表（每页 20 条，PRD §13.2 / R3-A04）。"""
    console = ctx.console
    profile = _load_profile(ctx, name)
    if profile is None:
        return None
    if not profile.mods:
        console.line(t("manage.one.empty"))
        return None
    page = 1
    while True:
        entries, pages = page_of(profile, page, size=PAGE_SIZE)
        console.line(t("manage.view.title", name=profile.name, count=len(profile.mods),
                       page=page, pages=pages))
        console.line()
        _print_table(console, _table_rows(entries, offset=(page - 1) * PAGE_SIZE))
        console.line()
        console.line(t("manage.view.hint"))
        kind, value = read_line(prompter, t("menu.prompt"))
        if kind == QUIT:
            return QUIT
        if kind == BACK:
            return None
        low = value.lower()
        if low == "b":
            return None
        if low == "n":
            if page >= pages:
                console.line(t("manage.view.last_page"))
            else:
                page += 1
        elif low == "p":
            if page <= 1:
                console.line(t("manage.view.first_page"))
            else:
                page -= 1
        else:
            console.line(t("menu.invalid_choice"))


def candidate_text(entries) -> str:
    """候选建议文本：地毯（modid=carpet）、钠（modid=sodium）。"""
    return "、".join(t("manage.candidate.item", name=display_name_of(entry),
                       modid=entry.mod_id or entry.key) for entry in entries)


def _resolve_targets(profile, selectors: list[str]) -> tuple[list[ModEntry], list[str]]:
    """把用户输入的一串定位串解析成 (命中条目, 未命中串)。"""
    targets: list[ModEntry] = []
    missing: list[str] = []
    for text in selectors:
        result = resolve_selector(profile, text)
        if result.entry is None:
            missing.append(text)
            continue
        if not any(item is result.entry for item in targets):
            targets.append(result.entry)
    return targets, missing


def _op_remove(ctx: AppContext, prompter: Prompter, name: str) -> str | None:
    """[2] 删除模组（逐条列出 + 默认 N，PRD §13.2 / R3-A05）。"""
    console = ctx.console
    profile = _load_profile(ctx, name)
    if profile is None:
        return None
    if not profile.mods:
        console.line(t("manage.one.empty"))
        return None
    console.line(t("manage.remove.prompt1"))
    kind, value = read_line(prompter, t("manage.remove.prompt2"))
    if kind == QUIT:
        return QUIT
    if kind == BACK or not value:
        return None
    selectors = [part.strip() for part in value.split(",") if part.strip()]
    targets, missing = _resolve_targets(profile, selectors)
    for text in missing:
        result = resolve_selector(profile, text)
        if result.candidates:
            console.line(t("manage.remove.not_found_hint", profile=profile.name, name=text,
                           suggest=candidate_text(result.candidates)))
        else:
            console.line(t("manage.remove.not_found", profile=profile.name, name=text))
    if not targets:
        return None
    console.line(t("manage.remove.title", profile=profile.name, count=len(targets)))
    for entry in targets:
        console.line(t("manage.remove.item", name=display_name_of(entry),
                       modid=entry.mod_id or entry.key))
    console.line()
    console.line(t("manage.remove.note"))
    # 危险操作的默认答案必须是 No（PRD §13.4 第 2 条）
    if not prompter.confirm(t("manage.remove.confirm"), default=False):
        console.line(t("manage.remove.cancelled"))
        return None
    result = remove_mods(profile, selectors)
    if not result.changed:
        console.line(t("manage.remove.none", profile=profile.name))
        return None
    path = profile_path(ctx.profiles_dir, name)
    try:
        save_profile(result.profile, path)
    except (ModcheckError, OSError):
        # 内存与磁盘都不变（新对象直接丢弃）
        console.line(t("manage.save_failed", path=path))
        return None
    console.line(t(result.message_key, **result.message_args))
    return None


def modrinth_provider(ctx: AppContext):
    """当前会话的 Modrinth 数据源；拿不到（未启用）返回 None。"""
    registry = ctx.registry
    if registry is None:
        return None
    provider = registry.by_name("modrinth")
    if provider is None or not provider.available:
        return None
    return provider


def _save_or_report(ctx: AppContext, path, profile) -> bool:
    """写盘；失败时打印统一 ✗ 文案并返回 False（内存与磁盘都不变）。"""
    try:
        save_profile(profile, path)
    except (ModcheckError, OSError):
        ctx.console.line(t("manage.save_failed", path=path))
        return False
    return True


def _op_set_source(ctx: AppContext, prompter: Prompter, name: str) -> str | None:
    """[3] 指定平台项目（用 provider 校验存在后再写回，PRD §13.2 / R3-A06）。"""
    console = ctx.console
    profile = _load_profile(ctx, name)
    if profile is None:
        return None
    if not profile.mods:
        console.line(t("manage.one.empty"))
        return None
    kind, selector = read_line(prompter, t("manage.source.pick"))
    if kind == QUIT:
        return QUIT
    if kind == BACK or not selector:
        return None
    found = resolve_selector(profile, selector)
    if found.entry is None:
        _report_missing(console, profile.name, selector, found.candidates)
        return None
    kind, raw = read_line(prompter, t("manage.source.prompt"))
    if kind == QUIT:
        return QUIT
    if kind == BACK or not raw:
        return None
    slug = parse_project_selector(raw)
    if slug is None:
        console.line(t("manage.source.bad_input", value=raw))
        return None
    provider = modrinth_provider(ctx)
    if provider is None:
        console.line(t("manage.source.network"))
        return None
    try:
        info = provider.get_project(slug)
    except ProviderError:
        # 断网/超时/5xx 一律当作"暂时校验不了"，清单绝不能被改
        console.line(t("manage.source.network"))
        return None
    if info is None:
        console.line(t("manage.source.not_found", slug=slug))
        return None
    result = set_source(profile, selector, provider="modrinth", slug=slug, title=info.title)
    if not result.changed:
        console.line(t("screen.not_found_entry", selector=selector))
        return None
    if not _save_or_report(ctx, profile_path(ctx.profiles_dir, name), result.profile):
        return None
    console.line(t(result.message_key, **result.message_args))
    return None


def _report_missing(console, profile_name: str, selector: str, candidates) -> None:
    """定位不到的两种文案（有候选 / 没候选）。"""
    if candidates:
        console.line(t("manage.remove.not_found_hint", profile=profile_name, name=selector,
                       suggest=candidate_text(candidates)))
        return
    console.line(t("manage.remove.not_found", profile=profile_name, name=selector))


def _op_ignore(ctx: AppContext, prompter: Prompter, name: str) -> str | None:
    """[4] 忽略 / 取消忽略模组（PRD §13.2 / R3-A07）。"""
    console = ctx.console
    profile = _load_profile(ctx, name)
    if profile is None:
        return None
    if not profile.mods:
        console.line(t("manage.one.empty"))
        return None
    kind, selector = read_line(prompter, t("manage.ignore.pick"))
    if kind == QUIT:
        return QUIT
    if kind == BACK or not selector:
        return None
    found = resolve_selector(profile, selector)
    if found.entry is None:
        _report_missing(console, profile.name, selector, found.candidates)
        return None
    console.line(t("manage.ignore.menu1"))
    console.line(t("manage.ignore.menu2"))
    tries = 0
    choice = ""
    while True:
        kind, value = read_line(prompter, t("manage.ignore.ask"))
        if kind == QUIT:
            return QUIT
        if kind == BACK:
            return None
        if value in ("1", "2"):
            choice = value
            break
        tries += 1
        console.line(t("menu.invalid_choice"))
        if tries >= MAX_INVALID_TRIES:
            console.line(t("screen.too_many_invalid"))
            return None
    result = set_ignored(profile, selector, choice == "1")
    if not result.changed:
        # 幂等：已经是这个状态，也要给用户一句明确的回执，但不写盘
        console.line(t(result.message_key, **result.message_args))
        return None
    if not _save_or_report(ctx, profile_path(ctx.profiles_dir, name), result.profile):
        return None
    console.line(t(result.message_key, **result.message_args))
    return None


def _op_rename(ctx: AppContext, prompter: Prompter, name: str) -> str | None:
    """[r] 重命名清单（文件名与 profile.name 同时更新，PRD §13.2 / R3-A08）。

    成功时返回**新清单名**，管理屏据此换到新名字继续管理（否则下一次读屏会报"读不了"）。
    """
    console = ctx.console
    profile = _load_profile(ctx, name)
    if profile is None:
        return None
    kind, value = read_line(prompter, t("manage.rename.prompt", chars=invalid_chars_text()))
    if kind == QUIT:
        return QUIT
    if kind == BACK or not value:
        return None
    try:
        result = rename(profile, value)          # 校验非法字符 + 造新对象
    except ConfigError as exc:
        console.line(exc.message)
        return None
    if not result.changed:
        console.line(t(result.message_key, **result.message_args))
        return None
    source = profile_path(ctx.profiles_dir, name)
    target = profile_path(ctx.profiles_dir, value.strip())
    if target.exists():
        # 绝不覆盖已有清单
        console.line(t("manage.rename.exists", name=value.strip()))
        return None
    try:
        save_profile(result.profile, target)
    except (ModcheckError, OSError):
        console.line(t("manage.rename.failed", path=target))
        return None
    try:
        delete_profile(source)
    except (ModcheckError, OSError):
        # 新清单已经写好了，只是旧文件删不掉（Windows 上只读文件就是这样）：
        # 必须说清楚，否则用户会看到两个清单
        console.line(t("manage.rename.partial", path=source))
        return None
    console.line(t(result.message_key, **result.message_args))
    return value.strip()          # 让管理屏改用新名字继续管这份清单


def _op_delete(ctx: AppContext, prompter: Prompter, name: str) -> str | None:
    """[d] 删除清单（必须完整输入清单名，PRD §13.2 / R3-A09）。

    删除成功后返回 BACK（清单已经不在了，留在这个屏只会报"读不了"）。
    """
    console = ctx.console
    profile = _load_profile(ctx, name)
    if profile is None:
        return None
    console.line(t("manage.delete.warn1", name=profile.name, count=len(profile.mods)))
    console.line(t("manage.delete.warn2"))
    console.line(t("manage.delete.warn3"))
    console.line()
    console.line(t("manage.delete.ask", name=profile.name))
    kind, value = read_line(prompter, t("manage.delete.prompt"))
    if kind == QUIT:
        return QUIT
    # 双重保险：名称必须**完整一致**（大小写敏感），b 与任何不符输入都取消
    if kind != KIND_OK or value != profile.name:
        console.line(t("manage.delete.cancel", value=value or "b", name=profile.name))
        return None
    path = profile_path(ctx.profiles_dir, name)
    try:
        delete_profile(path)
    except OSError:
        console.line(t("manage.delete.failed", path=path))
        return None
    left = len(list_profiles(ctx.profiles_dir))
    console.line(t("manage.delete.done", name=profile.name, left=left))
    return BACK                   # 清单没了，回列表屏


#: 按键 -> 处理函数（R3-A04~A09）；返回 QUIT 表示直接回主菜单
MANAGE_HANDLERS: dict[str, Callable[[AppContext, Prompter, str], str | None]] = {
    "1": _op_view,
    "2": _op_remove,
    "3": _op_set_source,
    "4": _op_ignore,
    "r": _op_rename,
    "d": _op_delete,
}


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
