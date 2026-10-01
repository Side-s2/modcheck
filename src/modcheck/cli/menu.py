"""交互式编号菜单（无参数启动时进入）。"""
from __future__ import annotations

import argparse
from typing import Sequence

from modcheck import __version__
from modcheck.cli.context import AppContext, build_context
from modcheck.cli.prompts import Choice, Prompter
from modcheck.console import Console
from modcheck.core.models import Loader
from modcheck.errors import ModcheckError, ProviderError, UserCancelled
from modcheck.i18n import t
from modcheck.storage.profiles import list_profiles

#: 主菜单（PRD §5.2 的编号顺序）
MENU_ITEMS = (
    ("1", "menu.item.check"),
    ("2", "menu.item.scan"),
    ("3", "menu.item.manage"),
    ("4", "menu.item.settings"),
    ("5", "menu.item.versions"),
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
    if not args.mc:
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


def run_menu(args: argparse.Namespace) -> int:
    """主菜单循环；主菜单里 Ctrl+C 退出（130），子流程里 Ctrl+C 回主菜单。"""
    console = Console(color="never" if getattr(args, "no_color", False) else "auto")
    ctx = build_context(args, console)
    prompter = Prompter(out=console)
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
                from modcheck.cli.commands.misc import run_config

                run_config(argparse.Namespace(action="show", key=None, value=None), ctx)
            elif choice == "5":
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


def _menu_check(args: argparse.Namespace, ctx: AppContext, prompter: Prompter) -> None:
    """功能①：交互式检查。"""
    from modcheck.cli.commands.check import run_check

    profiles = list_profiles(ctx.profiles_dir)
    if not profiles:
        if prompter.confirm(t("menu.need_profile")):
            _menu_scan(ctx, prompter)
        return
    console = ctx.console
    options = [Choice(key=summary.name,
                      label=summary.name + "（" + str(summary.mod_count) + " 个模组）")
               for summary in profiles]
    selected = prompter.choose(t("profile.list.header", count=len(profiles),
                                 dir=ctx.profiles_dir), options, allow_back=True)
    if selected in ("b", "q"):
        return
    args.profile = selected
    if not args.mc:
        args.mc = ctx.settings.default_mc_version
    if not _ask_target(args, ctx, prompter):
        return
    console.line()
    run_check(args, ctx)


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
    """功能③：清单列表。"""
    from modcheck.cli.commands.profile import run_profile

    run_profile(argparse.Namespace(action="list", name=None, target=None, json_out=False), ctx)


__all__ = ["run_menu", "print_banner", "print_menu", "MENU_ITEMS"]
