"""T-17 参数解析与退出码矩阵（PRD §10.4；验收清单 H 组会逐条核对）。

关键契约：用法错误 = 3，绝不能是 2（2 的语义是"有未判定项、无阻塞项"）。
"""
from __future__ import annotations

import pytest

from modcheck.cli.main import build_parser, main
from modcheck.errors import EXIT_OK, EXIT_USAGE


def test_version_subcommand_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    """--version 打印 modcheck <版本> 并返回 0。"""
    assert main(["--version"]) == EXIT_OK
    captured = capsys.readouterr()
    assert "modcheck 0.1.0" in (captured.out + captured.err)


def test_help_is_chinese_and_returns_zero(capsys: pytest.CaptureFixture[str]) -> None:
    """--help 全中文（含"用法："前缀）且返回 0。"""
    assert main(["--help"]) == EXIT_OK
    text = capsys.readouterr().out
    assert "用法：" in text
    assert "usage:" not in text
    assert "检查模组兼容性" in text


@pytest.mark.parametrize("argv", [
    ["--bogus"],
    ["frobnicate"],
    ["check", "--loader", "bukkit"],
    ["check", "--mc"],
])
def test_usage_errors_exit_3(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    """未知参数 / 未知子命令 / 非法 choices 一律退出 3（不是 2、不是 70）。"""
    assert main(argv) == EXIT_USAGE
    capsys.readouterr()


def test_parser_has_all_subcommands() -> None:
    """六个子命令一个都不能少（PRD §10.1）。"""
    parser = build_parser()
    subparsers = [action for action in parser._actions if hasattr(action, "choices")
                  and action.dest == "command"]
    assert subparsers, "没有找到子命令解析器"
    names = set(subparsers[0].choices)
    assert names == {"check", "scan", "profile", "versions", "config", "cache"}


@pytest.mark.parametrize("args", [
    ["check", "--profile", "x", "--file", "y"],
])
def test_check_accepts_documented_flags(args: list[str]) -> None:
    """check 的参数能被解析（互斥校验在命令层做）。"""
    parser = build_parser()
    namespace = parser.parse_args(args)
    assert namespace.profile == "x"
    assert namespace.file == "y"
