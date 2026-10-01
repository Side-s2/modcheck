"""菜单路径回归测试（P0：无参数 → 菜单 → 功能① 曾经 100% 崩溃）。

覆盖主 Agent 要求的 3 条：
  1) 无参数 + 注入输入「1 → 选清单」不抛异常
  2) 菜单 5 个入口逐个走一遍都不抛异常
  3) 菜单路径与等价的子命令路径给出**相同结论**
"""
from __future__ import annotations

import io
from argparse import Namespace
from pathlib import Path

import pytest

from fakes import FakeClock, FakeProvider, FakeTransport
from modcheck.cli.context import AppContext
from modcheck.cli.main import build_parser
from modcheck.cli.menu import run_menu
from modcheck.cli.commands.check import run_check
from modcheck.console import Console
from modcheck.core.models import Loader, ModEntry, ProjectHit, Settings, VersionInfo
from modcheck.errors import ProviderNetworkError
from modcheck.providers.http import HttpConfig, HttpClient
from modcheck.providers.registry import ProviderRegistry
from modcheck.storage.profiles import new_profile, profile_path, save_profile


def feed(values: list[str]):
    """把一串输入变成 input_fn（用完后返回 q）。"""
    queue = list(values)

    def _input(_prompt: str = "") -> str:
        return queue.pop(0) if queue else "q"

    return _input


def offline_client() -> HttpClient:
    """永远连不上的客户端（让 Mojang 清单拉取优雅降级，避免联网）。"""
    def handler(method, url, data, index):
        raise ProviderNetworkError("offline")

    return HttpClient(HttpConfig(rate_limit_per_min=100000), transport=FakeTransport(handler))


def make_ctx(tmp_path: Path, provider: FakeProvider) -> AppContext:
    """带假数据源的上下文。"""
    return AppContext(settings=Settings(), config_dir=tmp_path,
                      console=Console(stream=io.StringIO(), color="never", width=100),
                      registry=ProviderRegistry(providers=[provider]), cache=None,
                      client=offline_client(), prompter=None, interactive=True)


def write_profile(tmp_path: Path, entries: list[ModEntry]) -> Path:
    """写一份清单到 ctx 使用的 profiles 目录。"""
    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)
    profile = new_profile("demo")
    profile.mods = entries
    path = profile_path(tmp_path / "profiles", "demo")
    save_profile(profile, path)
    return path


def menu_args(tmp_path: Path) -> Namespace:
    """模拟 main() 在无子命令时交给菜单的 Namespace（含补齐后的默认值）。"""
    parser = build_parser()
    args = parser.parse_args(["--config-dir", str(tmp_path)])
    from modcheck.cli.main import apply_menu_defaults

    apply_menu_defaults(args, parser)
    return args


def version(number: str = "26.3") -> VersionInfo:
    """构造一个支持 26.3 的版本。"""
    return VersionInfo.from_api({"id": "V1", "project_id": "carpet", "version_number": number,
                                 "name": number, "date_published": "2026-09-18T00:00:00Z",
                                 "version_type": "release", "game_versions": ["26.3"],
                                 "loaders": ["fabric"], "files": []})


def test_menu_defaults_are_applied(tmp_path: Path) -> None:
    """main 会把 check 的默认值补进顶层 Namespace（P0 的根因）。"""
    args = menu_args(tmp_path)
    for name in ("mc", "loader", "profile", "file", "mods_dir", "json_out", "md_out",
                 "csv_out", "window", "resolve", "refresh", "pre", "jobs", "yes"):
        assert hasattr(args, name), name
    assert args.mc is None
    # quiet / no-color 用 SUPPRESS 默认值（故意不写进 Namespace），
    # 读取方一律用 getattr(..., False)，所以不在这里断言


def test_menu_check_path_does_not_crash(tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """回归：无参数 → 菜单 [1] → 选清单 → 不抛 AttributeError。"""
    from modcheck.cli import main as main_module

    write_profile(tmp_path, [ModEntry(key="carpet", display_name="Carpet", mod_id="carpet",
                                      sources={"modrinth": "carpet"})])
    inputs = feed(["1", "1", "q", "0"])
    monkeypatch.setattr("builtins.input", lambda prompt="": inputs())
    # main 现在要求 stdin 是终端才进菜单（非 TTY 会直接给中文提示并退出 3）
    monkeypatch.setattr("sys.stdin", _FakeTty())
    code = main_module.main(["--config-dir", str(tmp_path), "--no-color"])
    assert code == 0


class _FakeTty:
    """假装是交互式终端（只实现 isatty）。"""

    def isatty(self) -> bool:
        return True

    def readline(self) -> str:
        return ""

    def read(self, _size: int = -1) -> str:
        return ""


@pytest.mark.parametrize("choice", ["1", "2", "3", "4", "5"])
def test_every_menu_entry_runs(choice: str, tmp_path: Path) -> None:
    """菜单 5 个入口逐个走一遍：都不许抛异常。"""
    provider = FakeProvider(releases={"carpet": [version()]})
    ctx = make_ctx(tmp_path, provider)
    write_profile(tmp_path, [ModEntry(key="carpet", display_name="Carpet", mod_id="carpet",
                                      sources={"modrinth": "carpet"})])
    inputs = feed([choice, "1", "26.3", "fabric", "b", "0"])
    code = run_menu(menu_args(tmp_path), input_fn=inputs, ctx=ctx)
    assert code == 0


def test_menu_matches_subcommand_conclusion(tmp_path: Path) -> None:
    """菜单路径与等价子命令路径必须给出相同的汇总数字（同一张脸）。"""
    entry = ModEntry(key="carpet", display_name="Carpet", mod_id="carpet",
                     sources={"modrinth": "carpet"})
    write_profile(tmp_path, [entry])

    # 子命令路径
    ctx_a = make_ctx(tmp_path, FakeProvider(releases={"carpet": [version()]}))
    path = profile_path(tmp_path / "profiles", "demo")
    args_a = Namespace(profile=None, file=str(path), mods_dir=None, mc="26.3", loader="fabric",
                       json_out=None, md_out=None, csv_out=None, refresh=False, jobs=None,
                       yes=True, pre=False, quiet=True, window=25, debug=False, no_color=True,
                       resolve=False)
    run_check(args_a, ctx_a)
    summary_a = [line for line in ctx_a.console.stream.getvalue().splitlines()
                 if line.startswith("汇总：")]

    # 菜单路径（同样的清单、同样的目标版本与加载器）
    ctx_b = make_ctx(tmp_path, FakeProvider(releases={"carpet": [version()]}))
    inputs = feed(["1", "1", "26.3", "fabric", "0"])
    run_menu(menu_args(tmp_path), input_fn=inputs, ctx=ctx_b)
    summary_b = [line for line in ctx_b.console.stream.getvalue().splitlines()
                 if line.startswith("汇总：")]

    assert summary_a, "子命令路径没有输出汇总行"
    assert summary_a == summary_b


def test_menu_scan_entry_asks_and_backs_out(tmp_path: Path) -> None:
    """[2] 扫描：输入 b 返回主菜单，不抛异常。"""
    ctx = make_ctx(tmp_path, FakeProvider())
    code = run_menu(menu_args(tmp_path), input_fn=feed(["2", "b", "0"]), ctx=ctx)
    assert code == 0


def test_menu_quit_returns_zero(tmp_path: Path) -> None:
    """[0] 退出返回 0。"""
    ctx = make_ctx(tmp_path, FakeProvider())
    assert run_menu(menu_args(tmp_path), input_fn=feed(["0"]), ctx=ctx) == 0
