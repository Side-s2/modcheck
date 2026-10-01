"""R3-A16：屏幕级验收（列表→管理→6 个操作、7 个设置项、重置、5 类错误输入）。

全部用注入 input_fn 的方式，不依赖真实 TTY（任务书 §0 硬约束 3）。
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from fakes import FakeProvider

from modcheck.cli.context import AppContext
from modcheck.cli.prompts import Prompter
from modcheck.cli.screens_profiles import run_profiles_screen
from modcheck.cli.screens_settings import run_settings_screen
from modcheck.console import Console
from modcheck.core.models import ModEntry, ProjectInfo, Settings
from modcheck.errors import UserCancelled
from modcheck.providers.registry import ProviderRegistry
from modcheck.storage.profiles import load_profile, new_profile, profile_path, save_profile


def feed(values: list[str], prompts: list[str] | None = None):
    """注入输入序列；用完后一律返回 q。"""
    queue = list(values)

    def _input(prompt: str = "") -> str:
        if prompts is not None:
            prompts.append(prompt)
        return queue.pop(0) if queue else "q"

    return _input


def carpet_provider() -> FakeProvider:
    """以 modrinth 身份注册的假数据源（指定平台项目要用）。"""
    project = ProjectInfo(project_id="P1", slug="carpet", title="Carpet", description="",
                          project_type="mod", loaders=("fabric",), game_versions=("26.3",),
                          downloads=1, version_count=3)
    provider = FakeProvider(projects={"carpet": project})
    provider.name = "modrinth"
    provider.display_name = "Modrinth"
    return provider


def make_ctx(tmp_path: Path, values: list[str], prompts: list[str] | None = None) -> AppContext:
    """只有控制台 / 输入 / 假数据源的上下文（Mojang 拉不到 -> 版本屏走手动输入）。"""
    from fakes import FakeTransport
    from modcheck.errors import ProviderNetworkError
    from modcheck.providers.http import HttpConfig, HttpClient

    def handler(method: str, url: str, data, index: int):
        raise ProviderNetworkError("offline")

    console = Console(stream=io.StringIO(), color="never", width=100)
    client = HttpClient(HttpConfig(rate_limit_per_min=100000), transport=FakeTransport(handler))
    return AppContext(settings=Settings(), config_dir=tmp_path, console=console,
                      registry=ProviderRegistry(providers=[carpet_provider()]), cache=None,
                      client=client, interactive=True,
                      prompter=Prompter(input_fn=feed(values, prompts), out=console))


def out(ctx: AppContext) -> str:
    """取屏幕输出。"""
    return ctx.console.stream.getvalue()      # type: ignore[attr-defined]


def write_profile(tmp_path: Path, name: str = "服务器A", count: int = 4) -> Path:
    """写一份清单（带中文名，验证「[中文名] 英文名」格式）。"""
    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)
    profile = new_profile(name)
    profile.mods = [
        ModEntry(key="m" + str(i), display_name="Mod" + str(i), mod_id="m" + str(i),
                 cn_name="模" + str(i), sources={"modrinth": "m" + str(i)},
                 current_version="1.0")
        for i in range(count)
    ]
    path = profile_path(tmp_path / "profiles", name)
    save_profile(profile, path)
    return path


# ---------------------------------------------------------------- 黄金块
def test_list_screen_golden_block(tmp_path: Path) -> None:
    """列表屏整体排版与 PRD §13.2 逐字一致。"""
    write_profile(tmp_path, "服务器A", 120)
    ctx = make_ctx(tmp_path, ["q"])
    run_profiles_screen(ctx)
    lines = out(ctx).splitlines()
    assert lines[0] == "=== 管理模组清单 ==="
    assert lines[1] == "配置目录：" + str(tmp_path / "profiles")
    assert lines[2] == ""
    assert lines[3].startswith("[1] 服务器A（120 个模组，更新于 ") or lines[3].startswith(
        "  [1] 服务器A（120 个模组，更新于 ")
    assert lines[4] == ""
    assert lines[5] == "  [1-9] 打开某个清单进行管理"
    assert lines[6] == "  [n]   新建空清单"
    assert lines[7] == "  [q]   返回主菜单"


def test_manage_screen_golden_block(tmp_path: Path) -> None:
    """管理屏 8 行顺序与 PRD §13.2 逐字一致（6 个操作一个都不能少）。"""
    write_profile(tmp_path, "服务器A", 120)
    ctx = make_ctx(tmp_path, ["1", "b", "q"])
    run_profiles_screen(ctx)
    lines = out(ctx).splitlines()
    start = lines.index("=== 管理清单「服务器A」（120 个模组）===")
    assert lines[start:start + 9] == [
        "=== 管理清单「服务器A」（120 个模组）===",
        "  [1] 查看模组列表",
        "  [2] 删除模组",
        "  [3] 指定平台项目（手动匹配）",
        "  [4] 忽略 / 取消忽略模组",
        "  [r] 重命名这个清单",
        "  [d] 删除这个清单",
        "  [b] 返回清单列表",
        "  [q] 返回主菜单",
    ]


def test_settings_screen_golden_block(tmp_path: Path) -> None:
    """设置屏整体排版与 PRD §13.3 逐字一致。"""
    ctx = make_ctx(tmp_path, ["q"])
    run_settings_screen(ctx)
    lines = out(ctx).splitlines()
    assert lines[0] == "=== 设置 ==="
    assert lines[1] == "配置文件：" + str(tmp_path / "settings.json")
    assert lines[2] == ""
    assert lines[3:12] == [
        "  [1] 默认游戏版本       未设置",
        "  [2] 默认加载器         Fabric（fabric）",
        "  [3] 代理               未设置",
        "  [4] 颜色               auto（终端支持就用彩色）",
        "  [5] 并发数             6（上限 8）",
        "  [6] 缓存有效期         官方版本清单 24 小时 ｜ Modrinth 6 小时",
        "  [7] CurseForge API Key 未设置（本期未启用）",
        "  [8] 重置为默认设置",
        "  [q] 返回主菜单",
    ]


# ---------------------------------------------------------------- 一次会话走完 6 个操作
def test_full_profile_walkthrough(tmp_path: Path) -> None:
    """一次会话：进 [3] → 打开清单 → 6 个操作各来一次 → 回列表 → 回主菜单。"""
    write_profile(tmp_path, "服务器A", 4)
    values = [
        "1",            # 打开服务器A
        "1", "b",       # 查看模组列表 -> 返回
        "2", "1", "y",  # 删除模组 m0 -> 确认
        "3", "1", "carpet",   # 指定平台项目
        "4", "1", "1",  # 忽略
        "r", "主服",     # 重命名（管理屏要跟着换名字）
        "d", "主服",     # 删除清单（要输完整名称）
        "q",            # 回主菜单
    ]
    ctx = make_ctx(tmp_path, values)
    assert run_profiles_screen(ctx) == "quit"
    text = out(ctx)
    assert "清单「服务器A」的模组（共 4 个，第 1/1 页）：" in text
    assert "✓ 已删除 1 个模组，清单「服务器A」现在有 3 个模组。" in text
    assert "✓ 已把「[模1] Mod1」指定为 Modrinth 项目「Carpet」（carpet）。" in text
    assert "✓ 已忽略「[模1] Mod1」。" in text
    assert "✓ 清单「服务器A」已重命名为「主服」。" in text
    assert "=== 管理清单「主服」（3 个模组）===" in text      # 重命名后接着管新名字
    assert "✓ 清单「主服」已删除。还剩 0 个清单。" in text
    assert not (tmp_path / "profiles" / "主服.json").exists()


def test_view_table_shows_cn_name(tmp_path: Path) -> None:
    """查看列表的名称列用「[中文名] 英文名」（与报告一致）。"""
    write_profile(tmp_path, "服务器A", 1)
    ctx = make_ctx(tmp_path, ["1", "1", "b", "q"])
    run_profiles_screen(ctx)
    assert "[模0] Mod0" in out(ctx)


def test_settings_walkthrough_all_items(tmp_path: Path) -> None:
    """一次会话：7 个设置项各改一次 + 重置。"""
    values = [
        "1", "26.3",             # 默认游戏版本
        "2", "2",                # 默认加载器 -> NeoForge
        "3", "http://127.0.0.1:7890",   # 代理
        "4", "3",                # 颜色 -> never
        "5", "4",                # 并发数
        "6", "1", "12",          # 缓存：官方清单 12 小时
        "7", "abcd1234",         # CurseForge Key
        "8", "y",                # 重置
        "q",
    ]
    ctx = make_ctx(tmp_path, values)
    assert run_settings_screen(ctx) == "quit"
    text = out(ctx)
    for expected in ("✓ 默认游戏版本已设为 26.3。", "✓ 默认加载器已设为 NeoForge。",
                     "✓ 代理已设为 http://127.0.0.1:7890。", "✓ 颜色已设为 never。",
                     "✓ 并发数已设为 4。", "✓ 缓存有效期已设为 12 小时。",
                     "✓ CurseForge API Key 已保存（回显只显示后 4 位：****1234）。",
                     "✓ 设置已重置为默认值。"):
        assert expected in text, expected
    assert ctx.settings.to_dict() == Settings().to_dict()
    assert ctx.settings_path.exists()


# ---------------------------------------------------------------- 5 类错误输入
@pytest.mark.parametrize("bad", ["!@#", "", "9999", "b", "q"])
def test_five_error_inputs_profile_screen(bad: str, tmp_path: Path) -> None:
    """清单管理屏：5 类错误输入都不崩、不写盘。"""
    path = write_profile(tmp_path, "服务器A", 2)
    before = path.read_bytes()
    ctx = make_ctx(tmp_path, [bad, bad, bad, bad, "b", "q"])
    run_profiles_screen(ctx)
    assert path.read_bytes() == before


@pytest.mark.parametrize("bad", ["!@#", "", "9999", "b", "q"])
def test_five_error_inputs_settings_screen(bad: str, tmp_path: Path) -> None:
    """设置屏：5 类错误输入都不崩、不写盘。"""
    ctx = make_ctx(tmp_path, [bad, bad, bad, bad, "b", "q"])
    run_settings_screen(ctx)
    assert not ctx.settings_path.exists()


# ---------------------------------------------------------------- 不依赖真实 TTY
def test_screens_use_injected_input_only(tmp_path: Path, monkeypatch) -> None:
    """注入 input_fn 时绝不碰 builtins.input（碰了就直接失败，不会挂死）。"""
    def boom(*_args, **_kwargs):
        raise AssertionError("screens 不该直接调用 input()")

    monkeypatch.setattr("builtins.input", boom)
    write_profile(tmp_path, "服务器A", 1)
    ctx = make_ctx(tmp_path, ["1", "1", "b", "b", "q"])
    run_profiles_screen(ctx)
    ctx2 = make_ctx(tmp_path, ["q"])
    run_settings_screen(ctx2)


class _NotATty:
    """假装是重定向进来的 stdin。"""

    def isatty(self) -> bool:
        return False

    def readline(self) -> str:
        raise AssertionError("非交互终端下不该读到 stdin")

    def read(self, _size: int = -1) -> str:
        return ""


def test_prompter_refuses_to_ask_on_non_tty(monkeypatch) -> None:
    """非 TTY 且没注入 input_fn：提问必须立刻取消，绝不能挂死（硬约束 2）。"""
    monkeypatch.setattr(sys, "stdin", _NotATty())
    monkeypatch.setattr("builtins.input", lambda *a, **k: pytest.fail("不该提问"))
    with pytest.raises(UserCancelled):
        Prompter().ask("请选择 > ")


def test_injected_prompter_works_without_tty(monkeypatch) -> None:
    """注入 input_fn 时，即使 stdin 不是 TTY 也能正常走完（测试范式）。"""
    monkeypatch.setattr(sys, "stdin", _NotATty())
    ctx = make_ctx(tmp_path=Path("."), values=["q"])
    assert run_settings_screen(ctx) == "quit"
