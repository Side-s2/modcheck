"""R3-A14：每个输入点都必须能吃下 b / q / 非法输入 / 空串 / 超长编号。

验收口径（任务书 R3-A14）：不抛异常、不写盘、最终都能回到主菜单（退出码 0）。

「不写盘」的例外（这些是**合法输入**，会按设计写盘，已有专门用例覆盖）：
  * 新建 / 重命名清单：名字本身合法（例如 9999）就会真的建/改 -> 这里只用"一定写不成"的探针；
  * 代理：空串 = 清除（D42）会写盘 -> 这里只用非法格式的探针；
  * CurseForge API Key：任何文本都会存下来 -> 这里只用 b / q。
"""
from __future__ import annotations

import io
from argparse import Namespace
from pathlib import Path

import pytest
from fakes import FakeProvider, FakeTransport

from modcheck.cli.context import AppContext
from modcheck.cli.main import apply_menu_defaults, build_parser
from modcheck.cli.menu import run_menu
from modcheck.console import Console
from modcheck.core.models import ModEntry, ProjectInfo, Settings
from modcheck.errors import ProviderNetworkError
from modcheck.providers.http import HttpConfig, HttpClient
from modcheck.providers.registry import ProviderRegistry
from modcheck.storage.profiles import new_profile, profile_path, save_profile

#: 通用探针：b 返回 / q 回主菜单 / 非法串 / 空串 / 超长编号
PROBES = ["b", "q", "!@#", "", "9999"]
#: 名字类输入点的探针（9999 是合法清单名，会真的建/改，所以不在这里）
NAME_PROBES = ["b", "q", "", "a/b", 'a"b']
#: 代理的探针（空串是"清除"语义，会写盘）
PROXY_PROBES = ["b", "q", "!@#", "9999"]
#: API Key 的探针（任何文本都会存下来）
KEY_PROBES = ["b", "q"]

#: (输入点名称, 走到该输入点需要喂的按键, 探针表)
PROFILE_POINTS = (
    ("清单列表", ["3"], PROBES),
    ("手输清单名", ["3", "m"], PROBES),
    ("管理屏", ["3", "1"], PROBES),
    ("查看列表", ["3", "1", "1"], PROBES),
    ("删除模组-定位", ["3", "1", "2"], PROBES),
    ("删除模组-确认", ["3", "1", "2", "1"], PROBES),
    ("指定项目-定位", ["3", "1", "3"], PROBES),
    ("指定项目-slug", ["3", "1", "3", "1"], PROBES),
    ("忽略-定位", ["3", "1", "4"], PROBES),
    ("忽略-选择", ["3", "1", "4", "1"], PROBES),
    ("重命名清单", ["3", "1", "r"], NAME_PROBES),
    ("删除清单-确认", ["3", "1", "d"], PROBES),
    ("新建清单", ["3", "n"], NAME_PROBES),
)

SETTINGS_POINTS = (
    ("设置主屏", ["4"], PROBES),
    ("默认游戏版本", ["4", "1"], PROBES),
    ("默认加载器", ["4", "2"], PROBES),
    ("代理", ["4", "3"], PROXY_PROBES),
    ("颜色", ["4", "4"], PROBES),
    ("并发数", ["4", "5"], PROBES),
    ("缓存-选择", ["4", "6"], PROBES),
    ("缓存-小时", ["4", "6", "1"], PROBES),
    ("CurseForge Key", ["4", "7"], KEY_PROBES),
    ("重置设置", ["4", "8"], PROBES),
)


def feed(values: list[str]):
    """注入输入序列；用完后一律返回 q。"""
    queue = list(values)

    def _input(_prompt: str = "") -> str:
        return queue.pop(0) if queue else "q"

    return _input


def carpet_project() -> ProjectInfo:
    """一个能通过校验的假项目。"""
    return ProjectInfo(project_id="P1", slug="carpet", title="Carpet", description="",
                       project_type="mod", loaders=("fabric",), game_versions=("26.3",),
                       downloads=1, version_count=3)


def make_ctx(tmp_path: Path) -> AppContext:
    """离线上下文（Mojang 拉不到 -> 版本屏走手动输入）。"""

    def handler(method: str, url: str, data, index: int):
        raise ProviderNetworkError("offline")

    provider = FakeProvider(projects={"carpet": carpet_project()})
    provider.name = "modrinth"
    provider.display_name = "Modrinth"
    console = Console(stream=io.StringIO(), color="never", width=100)
    client = HttpClient(HttpConfig(rate_limit_per_min=100000), transport=FakeTransport(handler))
    return AppContext(settings=Settings(), config_dir=tmp_path, console=console,
                      registry=ProviderRegistry(providers=[provider]), cache=None,
                      client=client, interactive=True, prompter=None)


def menu_args(tmp_path: Path) -> Namespace:
    """模拟 main() 交给菜单的 Namespace。"""
    parser = build_parser()
    args = parser.parse_args(["--config-dir", str(tmp_path), "--no-color"])
    apply_menu_defaults(args, parser)
    return args


def write_profile(tmp_path: Path, name: str = "服务器A", count: int = 3) -> Path:
    """写一份清单。"""
    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)
    profile = new_profile(name)
    profile.mods = [ModEntry(key="m" + str(i), display_name="Mod" + str(i),
                             mod_id="m" + str(i), sources={"modrinth": "m" + str(i)})
                    for i in range(count)]
    path = profile_path(tmp_path / "profiles", name)
    save_profile(profile, path)
    return path


def snapshot(tmp_path: Path) -> dict[str, bytes]:
    """目录内容的快照（断言"不写盘"）。"""
    return {str(p.relative_to(tmp_path)): p.read_bytes()
            for p in sorted(tmp_path.rglob("*")) if p.is_file()}


PROFILE_CASES = [(name, prefix, probe) for name, prefix, probes in PROFILE_POINTS
                 for probe in probes]
SETTINGS_CASES = [(name, prefix, probe) for name, prefix, probes in SETTINGS_POINTS
                  for probe in probes]


@pytest.mark.parametrize("point,prefix,probe", PROFILE_CASES,
                         ids=[c[0] + "-" + repr(c[2]) for c in PROFILE_CASES])
def test_probe_at_every_profile_input(point: str, prefix: list[str], probe: str,
                                      tmp_path: Path) -> None:
    """清单管理屏：每个输入点注入探针，都不写盘且能回主菜单。"""
    write_profile(tmp_path)
    before = snapshot(tmp_path)
    values = prefix + [probe, "b", "b", "q", "0"]
    assert run_menu(menu_args(tmp_path), input_fn=feed(values), ctx=make_ctx(tmp_path)) == 0
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("point,prefix,probe", SETTINGS_CASES,
                         ids=[c[0] + "-" + repr(c[2]) for c in SETTINGS_CASES])
def test_probe_at_every_settings_input(point: str, prefix: list[str], probe: str,
                                       tmp_path: Path) -> None:
    """设置屏：每个输入点注入探针，都不写盘且能回主菜单。"""
    before = snapshot(tmp_path)
    values = prefix + [probe, "b", "b", "q", "0"]
    assert run_menu(menu_args(tmp_path), input_fn=feed(values), ctx=make_ctx(tmp_path)) == 0
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("probe", PROBES)
def test_probe_on_empty_profile_list(probe: str, tmp_path: Path) -> None:
    """没有任何清单时，[3] 的每个探针也不许崩、不许建文件。"""
    before = snapshot(tmp_path)
    values = ["3", probe, "b", "q", "0"]
    assert run_menu(menu_args(tmp_path), input_fn=feed(values), ctx=make_ctx(tmp_path)) == 0
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("probe", PROBES)
def test_probe_on_empty_profile(probe: str, tmp_path: Path) -> None:
    """空清单（0 个模组）时，四个模组操作都先判空。"""
    write_profile(tmp_path, count=0)
    before = snapshot(tmp_path)
    for action in ("1", "2", "3", "4"):
        values = ["3", "1", action, probe, "b", "b", "q", "0"]
        assert run_menu(menu_args(tmp_path), input_fn=feed(values),
                        ctx=make_ctx(tmp_path)) == 0
        assert snapshot(tmp_path) == before


def test_three_invalid_inputs_never_dead_end(tmp_path: Path) -> None:
    """连续非法输入 3 次后必须回上一层（规则：最多 3 次）。"""
    write_profile(tmp_path)
    values = ["3", "1", "9", "9", "9", "b", "q", "0"]
    assert run_menu(menu_args(tmp_path), input_fn=feed(values), ctx=make_ctx(tmp_path)) == 0


def test_quit_from_deep_screen_returns_to_main_menu(tmp_path: Path) -> None:
    """从最深处（删除清单确认）按 q 也要一步回主菜单。"""
    write_profile(tmp_path)
    values = ["3", "1", "d", "q", "0"]
    ctx = make_ctx(tmp_path)
    assert run_menu(menu_args(tmp_path), input_fn=feed(values), ctx=ctx) == 0
    text = ctx.console.stream.getvalue()      # type: ignore[attr-defined]
    assert "=== 管理模组清单 ===" in text


def test_valid_new_name_does_write(tmp_path: Path) -> None:
    """反面确认：合法的名字确实会写盘（证明上面的"不写盘"不是假绿）。"""
    values = ["3", "n", "9999", "q", "0"]
    assert run_menu(menu_args(tmp_path), input_fn=feed(values), ctx=make_ctx(tmp_path)) == 0
    assert (tmp_path / "profiles" / "9999.json").exists()
