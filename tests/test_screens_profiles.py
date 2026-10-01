"""R3-A03 / R3-A10：菜单 [3] 的清单列表屏、管理屏导航与新建空清单。"""
from __future__ import annotations

import io
from pathlib import Path

from modcheck.cli.context import AppContext
from modcheck.cli.prompts import Prompter
from modcheck.cli.screens_profiles import QUIT, run_profiles_screen
from modcheck.console import Console
from modcheck.core.models import ModEntry, Settings
from modcheck.storage.profiles import new_profile, profile_path, save_profile


def feed(values: list[str]):
    """注入输入序列；用完后一律返回 q（保证不会挂死）。"""
    queue = list(values)

    def _input(_prompt: str = "") -> str:
        return queue.pop(0) if queue else "q"

    return _input


def make_ctx(tmp_path: Path, values: list[str] | None = None) -> AppContext:
    """最小上下文：只需要 console / config_dir / prompter。"""
    console = Console(stream=io.StringIO(), color="never", width=100)
    return AppContext(settings=Settings(), config_dir=tmp_path, console=console,
                      registry=None, cache=None, client=None, interactive=True,
                      prompter=Prompter(input_fn=feed(list(values or ["q"])), out=console))


def out(ctx: AppContext) -> str:
    """取屏幕输出。"""
    return ctx.console.stream.getvalue()      # type: ignore[attr-defined]


def write_profile(tmp_path: Path, name: str, count: int = 1) -> Path:
    """写一份清单文件。"""
    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)
    profile = new_profile(name)
    profile.mods = [ModEntry(key="m" + str(i), display_name="Mod" + str(i), mod_id="m" + str(i))
                    for i in range(count)]
    path = profile_path(tmp_path / "profiles", name)
    save_profile(profile, path)
    return path


def test_list_screen_verbatim(tmp_path: Path) -> None:
    """列表屏逐字：标题 / 配置目录 / 条目 / [n] / [q]。"""
    write_profile(tmp_path, "服务器A", 120)
    ctx = make_ctx(tmp_path, ["q"])
    assert run_profiles_screen(ctx) == QUIT
    text = out(ctx)
    assert "=== 管理模组清单 ===" in text
    assert "配置目录：" in text and "profiles" in text
    assert "[1] 服务器A（120 个模组，更新于 " in text
    assert "  [1-9] 打开某个清单进行管理" in text
    assert "  [n]   新建空清单" in text
    assert "  [q]   返回主菜单" in text


def test_empty_list_screen_verbatim(tmp_path: Path) -> None:
    """没有任何清单时给专门的 ⚠ 文案。"""
    ctx = make_ctx(tmp_path, ["q"])
    run_profiles_screen(ctx)
    assert "⚠ 这里还没有任何模组清单。选 [n] 新建一个，或回主菜单选 [2] 扫描 mods 文件夹。" in out(ctx)


def test_open_profile_back_to_list_then_quit(tmp_path: Path) -> None:
    """R3-A03 验收：进 [3] → 打开清单 1 → 管理屏 → b 回列表 → q 回主菜单。"""
    write_profile(tmp_path, "服务器A", 5)
    ctx = make_ctx(tmp_path, ["1", "b", "q"])
    assert run_profiles_screen(ctx) == QUIT
    text = out(ctx)
    assert "=== 管理清单「服务器A」（5 个模组）===" in text
    assert "  [b] 返回清单列表" in text
    assert "  [q] 返回主菜单" in text
    assert text.count("=== 管理模组清单 ===") == 2      # b 之后又画了一次列表屏


def test_open_by_full_name(tmp_path: Path) -> None:
    """超过 9 个清单时可以 [m] 输名字（大小写不敏感）。"""
    for index in range(11):
        write_profile(tmp_path, "清单" + str(index), 1)
    ctx = make_ctx(tmp_path, ["m", "清单10", "q", "q"])
    run_profiles_screen(ctx)
    assert "=== 管理清单「清单10」（1 个模组）===" in out(ctx)


def test_unknown_name_lists_available(tmp_path: Path) -> None:
    """手输不存在的清单名 -> 给出可用清单列表，不崩。"""
    write_profile(tmp_path, "服务器A", 1)
    ctx = make_ctx(tmp_path, ["m", "不存在的", "q"])
    run_profiles_screen(ctx)
    assert "✗ 没有名为「不存在的」的清单。可用的清单：服务器A" in out(ctx)


def test_invalid_choices_three_times_returns(tmp_path: Path) -> None:
    """非法输入最多问 3 次，然后回主菜单（没有死胡同）。"""
    write_profile(tmp_path, "服务器A", 1)
    ctx = make_ctx(tmp_path, ["!@#", "!@#", "!@#", "0"])
    assert run_profiles_screen(ctx) == QUIT
    assert "输入错误太多次，返回上一层。" in out(ctx)


def test_new_profile_creates_file(tmp_path: Path) -> None:
    """[n] 新建空清单（R3-A10）：文件创建、0 个模组、逐字成功文案。"""
    ctx = make_ctx(tmp_path, ["n", "服务器B", "q"])
    run_profiles_screen(ctx)
    path = tmp_path / "profiles" / "服务器B.json"
    assert path.exists()
    assert "✓ 已创建空清单「服务器B」（0 个模组）。可以回主菜单选 [2] 把 mods 文件夹的内容扫描进来。" in out(ctx)


def test_new_profile_rejects_bad_and_duplicate(tmp_path: Path) -> None:
    """非法名与重名各自给文案，都不写盘。"""
    write_profile(tmp_path, "服务器A", 1)
    ctx = make_ctx(tmp_path, ["n", "a/b", "服务器A", "服务器C", "q"])
    run_profiles_screen(ctx)
    text = out(ctx)
    assert "✗ 清单名不能为空" in text
    assert "✗ 已经有一个叫「服务器A」的清单了。换一个名字。" in text
    assert (tmp_path / "profiles" / "服务器C.json").exists()


def test_new_profile_appears_in_list(tmp_path: Path) -> None:
    """新建后立刻出现在列表屏（R3-A10 验收）。"""
    ctx = make_ctx(tmp_path, ["n", "服务器B", "q"])
    run_profiles_screen(ctx)
    assert "[1] 服务器B（0 个模组" in out(ctx)


def write_entries(tmp_path: Path, name: str, mods: list[ModEntry]) -> Path:
    """写一份带指定模组的清单。"""
    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)
    profile = new_profile(name)
    profile.mods = mods
    path = profile_path(tmp_path / "profiles", name)
    save_profile(profile, path)
    return path


def many_mods(count: int) -> list[ModEntry]:
    """造 count 条模组记录（modid = m0..mN）。"""
    return [ModEntry(key="m" + str(i), display_name="Mod" + str(i), mod_id="m" + str(i),
                     sources={"modrinth": "slug" + str(i)}, current_version="1.0")
            for i in range(count)]


# ---------------------------------------------------------------- R3-A04 查看模组列表
def test_view_list_first_page(tmp_path: Path) -> None:
    """第一页 20 条：标题给出 第 1/2 页，表头有「匹配」列，第 21 条不在这一页。"""
    write_entries(tmp_path, "服务器A", many_mods(30))
    ctx = make_ctx(tmp_path, ["1", "1", "q", "q"])
    run_profiles_screen(ctx)
    text = out(ctx)
    assert "清单「服务器A」的模组（共 30 个，第 1/2 页）：" in text
    assert "  [n] 下一页  [p] 上一页  [b] 返回" in text
    assert "匹配" in text and "未匹配" in text      # 表头 + 数据行的匹配列
    assert "m19" in text and "m20" not in text


def test_view_list_paging_and_boundaries(tmp_path: Path) -> None:
    """n 到第 2 页；再 n 提示最后一页；p 回第 1 页；再 p 提示第一页。"""
    write_entries(tmp_path, "服务器A", many_mods(30))
    ctx = make_ctx(tmp_path, ["1", "1", "n", "n", "p", "p", "p", "b", "q"])
    run_profiles_screen(ctx)
    text = out(ctx)
    assert "第 1/2 页" in text and "第 2/2 页" in text
    assert "已经是最后一页了。" in text
    assert "已经是第一页了。" in text
    assert "m29" in text


def test_view_empty_profile(tmp_path: Path) -> None:
    """空清单给专门文案（R3-A04 验收）。"""
    write_entries(tmp_path, "空清单", [])
    ctx = make_ctx(tmp_path, ["1", "1", "q"])
    run_profiles_screen(ctx)
    assert "这个清单里还没有模组。回上一层用 [b]，或回主菜单选 [2] 扫描 mods 文件夹。" in out(ctx)


def test_view_quit_returns_to_main_menu(tmp_path: Path) -> None:
    """查看屏里按 q 直接回主菜单（不是回管理屏）。"""
    write_entries(tmp_path, "服务器A", many_mods(3))
    ctx = make_ctx(tmp_path, ["1", "1", "q"])
    assert run_profiles_screen(ctx) == QUIT
    assert "m2" in out(ctx)


def test_view_invalid_choice_reprompts(tmp_path: Path) -> None:
    """查看屏里的非法输入就地重问，不退出。"""
    write_entries(tmp_path, "服务器A", many_mods(3))
    ctx = make_ctx(tmp_path, ["1", "1", "!@#", "q", "q"])
    run_profiles_screen(ctx)
    text = out(ctx)
    assert "✗ 没有这个选项，请重新选择。" in text
    assert text.count("清单「服务器A」的模组") == 2      # 非法输入后又画了一次


def test_broken_profile_is_listed_not_crashing(tmp_path: Path) -> None:
    """损坏的清单只显示错误，不影响其它清单（也不能崩）。"""
    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)
    (tmp_path / "profiles" / "坏.json").write_text("{ not json", encoding="utf-8")
    write_profile(tmp_path, "服务器A", 1)
    ctx = make_ctx(tmp_path, ["q"])
    assert run_profiles_screen(ctx) == QUIT
    text = out(ctx)
    assert "服务器A" in text and "坏" in text
