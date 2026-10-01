"""退出码矩阵（PRD §10.4；验收清单 H 组逐条核对）。

全部离线：参数类错误在联网之前就该被拦下。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from modcheck.cli.main import main
from modcheck.errors import EXIT_OK, EXIT_USAGE


def run(argv: list[str], tmp_path: Path) -> int:
    """带临时配置目录跑一次 main。"""
    return main(["--config-dir", str(tmp_path)] + argv)


@pytest.mark.parametrize(("argv", "expected"), [
    (["--version"], EXIT_OK),
    (["--help"], EXIT_OK),
    (["--bogus"], EXIT_USAGE),
    (["frobnicate"], EXIT_USAGE),
    (["check", "--loader", "bukkit"], EXIT_USAGE),
    (["check", "--mc"], EXIT_USAGE),
])
def test_matrix(argv: list[str], expected: int, tmp_path: Path,
                capsys: pytest.CaptureFixture[str]) -> None:
    """基础矩阵（含 argparse 层）。"""
    assert run(argv, tmp_path) == expected
    capsys.readouterr()


def test_check_without_source_exit_three(tmp_path: Path,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    """check 没给 --profile/--file/--mods-dir -> 用法错误 3（不是内部错误 70）。"""
    assert run(["check", "--mc", "26.3", "--loader", "fabric"], tmp_path) == EXIT_USAGE
    capsys.readouterr()


def test_check_bad_mc_exit_three_before_network(tmp_path: Path,
                                                capsys: pytest.CaptureFixture[str]) -> None:
    """--mc abc -> 3，且在联网之前就被拦下（不会先等一次网络请求）。"""
    profile = tmp_path / "demo.json"
    profile.write_text('{"schema_version": 1, "name": "demo", "mods": []}', encoding="utf-8")
    assert run(["check", "--file", str(profile), "--mc", "abc"], tmp_path) == EXIT_USAGE
    capsys.readouterr()


def test_check_snapshot_mc_exit_three(tmp_path: Path,
                                      capsys: pytest.CaptureFixture[str]) -> None:
    """--mc 26.4-snapshot-2 -> 3（PRD E08）。"""
    profile = tmp_path / "demo.json"
    profile.write_text('{"schema_version": 1, "name": "demo", "mods": []}', encoding="utf-8")
    code = run(["check", "--file", str(profile), "--mc", "26.4-snapshot-2"], tmp_path)
    assert code == EXIT_USAGE
    assert "快照" in capsys.readouterr().out


def test_check_empty_profile_exit_zero(tmp_path: Path,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    """空清单 -> 退出码 0 且给出专门的空结果文案（PRD E15）。"""
    profile = tmp_path / "demo.json"
    profile.write_text('{"schema_version": 1, "name": "demo", "mods": []}', encoding="utf-8")
    code = run(["check", "--file", str(profile), "--mc", "26.3", "--loader", "fabric",
                "--no-color"], tmp_path)
    assert code == EXIT_OK
    capsys.readouterr()


def test_profile_list_exit_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """profile（无参数）默认 list，正常退出。"""
    assert run(["profile"], tmp_path) == EXIT_OK
    capsys.readouterr()


def test_config_show_and_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """config show / path 正常退出。"""
    assert run(["config", "show"], tmp_path) == EXIT_OK
    assert run(["config", "path"], tmp_path) == EXIT_OK
    capsys.readouterr()


def test_config_unknown_key_exit_three(tmp_path: Path,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    """不认识的设置项 -> 3。"""
    assert run(["config", "set", "no.such.key", "1"], tmp_path) == EXIT_USAGE
    capsys.readouterr()


def test_cache_info_exit_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """cache info 正常退出。"""
    assert run(["cache", "info"], tmp_path) == EXIT_OK
    capsys.readouterr()
