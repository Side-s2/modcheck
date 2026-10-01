"""交互式编号菜单（无参数启动时进入）。"""
from __future__ import annotations

import argparse
from typing import Callable

from modcheck import __version__
from modcheck.cli.context import AppContext, build_context
from modcheck.cli.prompts import Choice, Prompter
from modcheck.console import Console
from modcheck.core.models import Loader
from modcheck.errors import ModcheckError, ProviderError, UserCancelled
from modcheck.i18n import t
from modcheck.storage.profiles import list_profiles

#: 主菜单（PRD §5.2 的编号顺序；[5] 是下载，原 [5] 版本列表按裁决 D46 顺延为 [6]）
MENU_ITEMS = (
    ("1", "menu.item.check"),
    ("2", "menu.item.scan"),
    ("3", "menu.item.manage"),
    ("4", "menu.item.settings"),
    ("5", "menu.item.download"),
    ("6", "menu.item.versions"),
    ("0", "menu.item.quit"),
)


def print_banner(ctx: AppContext) -> None:
    """启动横幅：版本 + 配置目录 + 数据源状态 + 无清单提示。"""
    console = ctx.console
    console.line(t("app.banner", version=__version__))
    console.line(t("app.config_dir", path=ctx.config_dir))
    modrinth, curseforge = ctx.registry.status_line()
    console.line(t("app.sources", modrinth=modrinth, curseforge=curseforge))
    if not list_profiles(ctx.profiles_dir):
        console.line(t("menu.hint.no_profile"))
    console.line()


def print_menu(ctx: AppContext) -> None:
    """打印编号菜单。"""
    for key, label_key in MENU_ITEMS:
        ctx.console.line(t("menu.title", index=key, label=t(label_key)))


def _ask_target(args: argparse.Namespace, ctx: AppContext, prompter: Prompter) -> bool:
    """交互式补齐目标版本与加载器；返回是否继续。"""
    if not getattr(args, "mc", None):
        raw = prompter.ask(t("cli.check.mc") + " > ")
        if raw in ("q", ""):
            return False
        args.mc = raw
    loaders = (Loader.FABRIC, Loader.NEOFORGE, Loader.FORGE)
    raw = prompter.ask(t("cli.check.loader") + " > ")
    if raw in ("q",):
        return False
    if raw:
        args.loader = Loader.parse(raw).value
    else:
        args.loader = ctx.settings.default_loader.value
    return True


def run_menu(args: argparse.Namespace, *, input_fn: Callable[[str], str] | None = None,
             console: Console | None = None, ctx: AppContext | None = None) -> int:
    """主菜单循环；主菜单里 Ctrl+C 退出（130），子流程里 Ctrl+C 回主菜单。

    参数：
        input_fn: 注入的输入函数（测试用；默认读标准输入）。
        console: 注入的控制台（测试用）。
        ctx: 注入的上下文（测试用；默认按 args 装配）。
    """
    if console is None:
        console = Console(color="never" if getattr(args, "no_color", False) else "auto")
    if ctx is None:
        ctx = build_context(args, console)
    prompter = Prompter(input_fn=input_fn, out=console)
    ctx.prompter = prompter
    ctx.interactive = True
    print_banner(ctx)
    while True:
        print_menu(ctx)
        try:
            choice = prompter.ask(t("menu.prompt"))
        except UserCancelled:
            console.line()
            return 130
        if choice in ("0", "q"):
            console.line(t("menu.bye"))
            return 0
        try:
            if choice == "1":
                _menu_check(args, ctx, prompter)
            elif choice == "2":
                _menu_scan(ctx, prompter)
            elif choice == "3":
                _menu_profiles(ctx)
            elif choice == "4":
                _menu_settings(ctx)
            elif choice == "5":
                _menu_download(args, ctx, prompter)
            elif choice == "6":
                from modcheck.cli.commands.misc import run_versions

                run_versions(argparse.Namespace(limit=10, json_out=False), ctx)
            else:
                console.line(t("menu.invalid_choice"))
        except UserCancelled:
            console.line()
            console.line(t("menu.invalid_choice"))
        except ModcheckError as exc:
            console.line(exc.message)
            if exc.hint:
                console.line(exc.hint)
        console.line()


def _profile_label(summary) -> str:
    """清单选项的文案（用户要求带上修改日期）。

    同名或相似的清单多起来以后，"哪个是我上周改过的"比"有几个模组"更能帮用户选对；
    日期取不到时退回不带日期的文案，绝不显示空白或 "None"。
    """
    stamp = (getattr(summary, "updated_at", "") or "").strip()
    short = stamp[:16].replace("T", " ")          # 2026-10-01T19:20:31 -> 2026-10-01 19:20
    if len(short) == 16:
        return t("profile.option", name=summary.name, count=summary.mod_count, date=short)
    return t("profile.option.nodate", name=summary.name, count=summary.mod_count)


def _prepare_check(args: argparse.Namespace, ctx: AppContext,
                   prompter: Prompter) -> int | None:
    """检查前的四屏（选清单 -> 目标版本 -> 加载器 -> 确认）；返回模组数。

    抽出来是因为 [1] 与 [5] 共用同一套前置屏：下载入口的前半段就是一次检查，
    两份实现迟早会漂移（例如以后加一个"数据源不可用"的确认，只改了一边）。
    None 表示用户回退了（含"没有清单"的情况）。
    """
    profiles = list_profiles(ctx.profiles_dir)
    if not profiles:
        if prompter.confirm(t("menu.need_profile")):
            _menu_scan(ctx, prompter)
        return None
    console = ctx.console
    options = [Choice(key=summary.name, label=_profile_label(summary)) for summary in profiles]
    selected = prompter.choose(t("profile.list.header", count=len(profiles),
                                 dir=ctx.profiles_dir), options, allow_back=True)
    if selected in ("b", "q"):
        return None
    args.profile = selected
    mod_count = next((s.mod_count for s in profiles if s.name == selected), 0)
    if not _screen_version(args, ctx, prompter):        # 屏②：选目标版本
        return None
    if not _screen_loader(args, ctx, prompter):          # 屏③：选加载器
        return None
    if not _screen_confirm(args, ctx, prompter, mod_count):   # 屏④：确认页
        console.line(t("menu.check.aborted"))
        return None
    return mod_count


def _menu_check(args: argparse.Namespace, ctx: AppContext, prompter: Prompter) -> None:
    """功能①：交互式检查。"""
    from modcheck.cli.commands.check import run_check

    if _prepare_check(args, ctx, prompter) is None:
        return
    ctx.console.line()
    run_check(args, ctx)


def _menu_download(args: argparse.Namespace, ctx: AppContext, prompter: Prompter) -> None:
    """功能⑤：检查并下载（PRD §14.4，R3-B04 ~ R3-B09）。

    前半段与 [1] 完全相同（同一套屏、同一个 run_check），只是顺手接住报告；
    后半段（询问 / 选文件夹 / 同名冲突 / 进度 / 汇总）全在 cli/screens_download.py，
    真正的下载在 flows/download_flow.py。
    """
    from modcheck.cli.commands.check import run_check
    from modcheck.cli.screens_download import post_check_download

    if _prepare_check(args, ctx, prompter) is None:
        return
    box: dict = {}
    ctx.console.line()
    run_check(args, ctx, on_outcome=lambda outcome: box.setdefault("outcome", outcome))
    outcome = box.get("outcome")
    if outcome is not None:
        post_check_download(ctx, outcome.report)


def _screen_version(args: argparse.Namespace, ctx: AppContext, prompter: Prompter, *,
                    allow_clear: bool = False) -> bool:
    """屏②：列出最近 10 个官方正式版让人编号选择（PRD §5.6）。

    allow_clear=True 时多给一个 [c]「清除（不设默认）」（设置屏 [1] 复用这块屏）：
    此时 args.mc 被设成空串，调用方据此清空默认版本。
    """
    if getattr(args, "mc", None):
        return True
    console = ctx.console
    releases: list[str] = []
    try:
        from modcheck.providers.mojang import MojangVersions

        releases = [item.version_id for item in MojangVersions(ctx.client).list_releases(limit=10)]
    except ProviderError:
        console.line(t("warn.mojang_unavailable"))
    if not releases:
        if allow_clear:
            console.line(t("menu.version.clear"))
        raw = prompter.ask(t("cli.check.mc") + " > ")
        if allow_clear and raw == "c":
            args.mc = ""
            return True
        if raw in ("b", "q", ""):
            return False
        args.mc = raw
        return True
    while True:
        console.line(t("menu.version.title"))
        for index, version in enumerate(releases, start=1):
            key = "menu.version.latest" if index == 1 else "menu.version.item"
            console.line(t(key, index=index, version=version))
        console.line(t("menu.version.manual"))
        if allow_clear:
            console.line(t("menu.version.clear"))
        console.line(t("menu.back"))
        raw = prompter.ask(t("menu.prompt"))
        if raw == "b" or raw == "q":
            return False
        if allow_clear and raw == "c":
            args.mc = ""
            return True
        if raw == "m":
            manual = prompter.ask(t("cli.check.mc") + " > ")
            if manual and manual not in ("b", "q"):
                args.mc = manual
                return True
            continue
        if raw.isdigit() and 1 <= int(raw) <= len(releases):
            args.mc = releases[int(raw) - 1]
            return True
        console.line(t("menu.invalid_choice"))


def _screen_loader(args: argparse.Namespace, ctx: AppContext, prompter: Prompter) -> bool:
    """屏③：选服务端加载器（PRD §5.6）。"""
    console = ctx.console
    loaders = (Loader.FABRIC, Loader.NEOFORGE, Loader.FORGE)
    while True:
        console.line(t("menu.loader.title"))
        for index, loader in enumerate(loaders, start=1):
            console.line(t("menu.loader.item", index=index, name=loader.display_name,
                           value=loader.value))
        console.line(t("menu.loader.default", name=ctx.settings.default_loader.display_name))
        console.line(t("menu.back"))
        raw = prompter.ask(t("menu.prompt")).lower()
        if raw in ("b", "q"):
            return False
        if raw == "d" or raw == "":
            args.loader = ctx.settings.default_loader.value
            return True
        if raw.isdigit() and 1 <= int(raw) <= len(loaders):
            args.loader = loaders[int(raw) - 1].value
            return True
        console.line(t("menu.invalid_choice"))


def _screen_confirm(args: argparse.Namespace, ctx: AppContext, prompter: Prompter,
                    mod_count: int) -> bool:
    """屏④：确认页 —— 真正发请求前的最后一道闸（PRD §5.6）。

    告诉用户"将检查几个模组、大概发多少次请求、大约多久"，
    这是用户判断"现在要不要跑"的唯一依据。估算按每模组 2 个请求、约 0.25~0.75 秒。
    """
    console = ctx.console
    loader = Loader.parse(str(args.loader))
    requests = max(2, mod_count * 2)
    low = max(3, int(mod_count * 0.25))
    high = max(8, int(mod_count * 0.75))
    console.line(t("menu.confirm.title"))
    console.line(t("menu.confirm.profile", name=args.profile, count=mod_count))
    console.line(t("menu.confirm.target", mc=args.mc, loader=loader.display_name))
    console.line(t("menu.confirm.sources"))
    console.line(t("menu.confirm.cost", requests=requests, low=low, high=high))
    return prompter.confirm(t("menu.confirm.ask"))


def _menu_settings(ctx: AppContext) -> None:
    """功能④：设置屏（R3-A11，PRD §13.3）。"""
    from modcheck.cli.screens_settings import run_settings_screen

    run_settings_screen(ctx)


def _menu_scan(ctx: AppContext, prompter: Prompter) -> None:
    """功能②：扫描 mods 文件夹。"""
    from modcheck.cli.commands.scan import run_scan

    raw = prompter.ask(t("cli.scan.paths") + " > ")
    if not raw or raw in ("b", "q"):
        return
    name = prompter.ask(t("cli.scan.profile") + " > ") or "demo"
    run_scan(argparse.Namespace(paths=[raw], profile=name, from_list=None, new=False,
                                yes=True), ctx)


def _menu_profiles(ctx: AppContext) -> None:
    """功能③：清单列表 + 管理屏（R3-A03，PRD §13.2）。"""
    from modcheck.cli.screens_profiles import run_profiles_screen

    run_profiles_screen(ctx)


__all__ = ["run_menu", "print_banner", "print_menu", "MENU_ITEMS"]
