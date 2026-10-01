"""argparse 顶层调度与退出码（PRD §10.1 / §10.4）。

职责：
  * 定义全部子命令与公共参数；
  * 把顶层异常映射成退出码（绝不打印 Python traceback）；
  * 无子命令时进入交互式菜单。
"""
from __future__ import annotations

import argparse
import sys
import traceback
from typing import Final, NoReturn, Sequence

from modcheck import APP_NAME, __version__
from modcheck.console import Console, init_terminal_encoding
from modcheck.errors import (EXIT_INTERNAL, EXIT_INTERRUPTED, EXIT_USAGE, ModcheckError)
from modcheck.i18n import t

#: 子命令 -> (模块名, 函数名)。延迟 import，保证 --help / --version 极快且无副作用。
_COMMANDS: Final[dict[str, tuple[str, str]]] = {
    "check": ("modcheck.cli.commands.check", "run_check"),
    "scan": ("modcheck.cli.commands.scan", "run_scan"),
    "profile": ("modcheck.cli.commands.profile", "run_profile"),
    "versions": ("modcheck.cli.commands.versions", "run_versions"),
    "config": ("modcheck.cli.commands.config", "run_config"),
    "cache": ("modcheck.cli.commands.cache", "run_cache"),
}

LOADER_CHOICES: Final[tuple[str, ...]] = ("fabric", "neoforge", "forge")


class ChineseHelpParser(argparse.ArgumentParser):
    """中文帮助 + 用法错误一律退出 3。

    argparse 默认用法错误返回 2，但本项目的 2 是"有未判定项、无阻塞项"
    （PRD §10.4），撞码会让脚本无法区分"参数写错"和"有几个模组没查到"，
    所以这里覆写 error() 强制走 EXIT_USAGE。
    """

    def error(self, message: str) -> "NoReturn":  # type: ignore[override]
        self.print_usage(sys.stderr)
        sys.stderr.write(t("cli.error.usage", detail=message) + "\n")
        self.exit(EXIT_USAGE)

    def format_usage(self) -> str:
        return super().format_usage().replace("usage:", t("cli.usage_prefix"), 1)

    def format_help(self) -> str:
        # argparse 在 format_help 里直接写死 "usage: " 前缀，只能在这里替换
        return super().format_help().replace("usage:", t("cli.usage_prefix"), 1)


def _decorate(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("-h", "--help", action="help", help=t("cli.help.help"))
    parser._positionals.title = t("cli.section.positional")  # noqa: SLF001
    parser._optionals.title = t("cli.section.options")  # noqa: SLF001
    return parser


def _new_parser(description: str, *, prog: str | None = None) -> ChineseHelpParser:
    parser = ChineseHelpParser(prog=prog, description=description, add_help=False,
                               formatter_class=argparse.RawDescriptionHelpFormatter)
    _decorate(parser)
    return parser


def _add_global_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--version", action="version",
                        version=APP_NAME + " " + __version__, help=t("cli.help.version"))
    parser.add_argument("--config-dir", default=None, metavar=t("cli.metavar.value"),
                        help=t("cli.help.config_dir"))
    parser.add_argument("--debug", action="store_true", help=t("cli.help.debug"))
    parser.add_argument("--no-color", action="store_true", help=t("cli.help.no_color"))


def _sub(sub: argparse._SubParsersAction, name: str) -> ChineseHelpParser:  # noqa: SLF001
    parser = sub.add_parser(name, help=t("cli.cmd." + name), description=t("cli.cmd." + name),
                            add_help=False, formatter_class=argparse.RawDescriptionHelpFormatter)
    _decorate(parser)
    return parser  # type: ignore[return-value]


def build_parser() -> argparse.ArgumentParser:
    """构造完整的命令行解析器。"""
    parser = _new_parser(t("cli.description"), prog=APP_NAME)
    _add_global_options(parser)
    sub = parser.add_subparsers(dest="command", metavar=t("cli.metavar.command"))

    check = _sub(sub, "check")
    check.add_argument("--profile", default=None, metavar=t("cli.metavar.value"), help=t("cli.check.profile"))
    check.add_argument("--file", default=None, metavar=t("cli.metavar.value"), help=t("cli.check.file"))
    check.add_argument("--mods-dir", dest="mods_dir", default=None, metavar=t("cli.metavar.value"), help=t("cli.check.mods_dir"))
    check.add_argument("--mc", default=None, metavar=t("cli.metavar.value"), help=t("cli.check.mc"))
    check.add_argument("--loader", default=None, choices=LOADER_CHOICES, help=t("cli.check.loader"))
    check.add_argument("--json", dest="json_out", default=None, metavar=t("cli.metavar.value"), help=t("cli.check.json"))
    check.add_argument("--md", dest="md_out", default=None, metavar=t("cli.metavar.value"), help=t("cli.check.md"))
    check.add_argument("--csv", dest="csv_out", default=None, metavar=t("cli.metavar.value"), help=t("cli.check.csv"))
    check.add_argument("--refresh", action="store_true", help=t("cli.check.refresh"))
    check.add_argument("--jobs", type=int, default=None, metavar=t("cli.metavar.value"), help=t("cli.check.jobs"))
    check.add_argument("--yes", action="store_true", help=t("cli.check.yes"))
    check.add_argument("--pre", action="store_true", help=t("cli.check.pre"))
    check.add_argument("--quiet", action="store_true", default=argparse.SUPPRESS, help=t("cli.help.quiet"))
    check.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS, help=t("cli.help.no_color"))
    check.add_argument("--window", type=int, default=None, metavar=t("cli.metavar.value"), help=t("cli.check.window"))

    scan = _sub(sub, "scan")
    scan.add_argument("paths", nargs="*", help=t("cli.scan.paths"))
    scan.add_argument("--from-list", dest="from_list", default=None, metavar=t("cli.metavar.value"), help=t("cli.scan.from_list"))
    scan.add_argument("--profile", default=None, metavar=t("cli.metavar.value"), help=t("cli.scan.profile"))
    scan.add_argument("--new", action="store_true", help=t("cli.scan.new"))
    scan.add_argument("--yes", action="store_true", help=t("cli.scan.yes"))
    scan.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS, help=t("cli.help.no_color"))

    profile = _sub(sub, "profile")
    profile.add_argument("action", nargs="?", default="list", help=t("cli.profile.action"))
    profile.add_argument("name", nargs="?", default=None, help=t("cli.profile.name"))
    profile.add_argument("target", nargs="?", default=None, help=t("cli.profile.target"))
    profile.add_argument("--json", dest="json_out", action="store_true", help=t("cli.profile.json"))
    profile.add_argument("--yes", action="store_true", help=t("cli.check.yes"))

    versions = _sub(sub, "versions")
    versions.add_argument("--limit", type=int, default=10, metavar=t("cli.metavar.value"), help=t("cli.versions.limit"))
    versions.add_argument("--json", dest="json_out", action="store_true", help=t("cli.versions.json"))

    config = _sub(sub, "config")
    config.add_argument("action", nargs="?", default="show", help=t("cli.config.action"))
    config.add_argument("key", nargs="?", default=None, help=t("cli.config.key"))
    config.add_argument("value", nargs="?", default=None, help=t("cli.config.value"))

    cache = _sub(sub, "cache")
    cache.add_argument("action", nargs="?", default="info", help=t("cli.cache.action"))
    cache.add_argument("--older-than", dest="older_than", default=None, metavar=t("cli.metavar.value"), help=t("cli.cache.older_than"))
    return parser


def _load_attr(module_path: str, attr: str) -> object:
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, attr)


def _dispatch(command: str, args: argparse.Namespace, console: Console) -> int:
    module_path, func_name = _COMMANDS[command]
    from modcheck.cli.context import build_context

    ctx = build_context(args, console)
    func = _load_attr(module_path, func_name)
    return int(func(args, ctx))  # type: ignore[operator]


def main(argv: Sequence[str] | None = None) -> int:
    """程序入口；返回进程退出码（PRD §10.4）。"""
    init_terminal_encoding()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # --help / --version / 用法错误：转成返回码，不抛
        return int(exc.code or 0)
    console = Console(color="never" if getattr(args, "no_color", False) else "auto",
                      quiet=bool(getattr(args, "quiet", False)))
    debug = bool(getattr(args, "debug", False))
    try:
        if args.command is None:
            run_menu = _load_attr("modcheck.cli.menu", "run_menu")
            return int(run_menu(args))  # type: ignore[operator]
        return _dispatch(str(args.command), args, console)
    except KeyboardInterrupt:
        console.line()
        return EXIT_INTERRUPTED
    except ModcheckError as exc:
        console.line(exc.message)
        if exc.hint:
            console.line(exc.hint)
        if debug:
            console.line(t("err.debug.traceback"))
            traceback.print_exc()
        return exc.exit_code
    except SystemExit:
        raise
    except Exception as exc:  # 顶层兜底：绝不把 traceback 甩给用户
        console.line(t("err.internal", detail=type(exc).__name__ + ": " + str(exc)))
        if debug:
            console.line(t("err.debug.traceback"))
            traceback.print_exc()
        return EXIT_INTERNAL


__all__ = ["main", "build_parser", "LOADER_CHOICES"]
