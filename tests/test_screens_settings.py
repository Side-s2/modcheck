"""R3-A11：菜单 [4] 设置屏的 7 个子项（注入假输入，不依赖 TTY）。"""
from __future__ import annotations

import io
import json
from argparse import Namespace
from pathlib import Path

from fakes import FakeTransport
from modcheck.cli.context import AppContext
from modcheck.cli.prompts import Prompter
from modcheck.cli.screens_settings import QUIT, run_settings_screen
from modcheck.console import Console
from modcheck.core.models import Loader, Settings
from modcheck.errors import ProviderNetworkError
from modcheck.providers.http import HttpConfig, HttpClient


def feed(values: list[str], prompts: list[str] | None = None):
    """注入输入序列；用完后一律返回 q。"""
    queue = list(values)

    def _input(prompt: str = "") -> str:
        if prompts is not None:
            prompts.append(prompt)
        return queue.pop(0) if queue else "q"

    return _input


def make_ctx(tmp_path: Path, values: list[str] | None = None,
             prompts: list[str] | None = None) -> AppContext:
    """离线上下文（Mojang 清单拉不到 -> 版本屏走手动输入）。"""

    def handler(method: str, url: str, data, index: int):
        raise ProviderNetworkError("offline")

    client = HttpClient(HttpConfig(rate_limit_per_min=100000), transport=FakeTransport(handler))
    console = Console(stream=io.StringIO(), color="never", width=100)
    return AppContext(settings=Settings(), config_dir=tmp_path, console=console,
                      registry=None, cache=None, client=client, interactive=True,
                      prompter=Prompter(input_fn=feed(list(values or ["q"]), prompts),
                                        out=console))


def out(ctx: AppContext) -> str:
    """取屏幕输出。"""
    return ctx.console.stream.getvalue()      # type: ignore[attr-defined]


def saved(ctx: AppContext) -> dict:
    """读回 settings.json。"""
    path = ctx.settings_path
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_settings_screen_verbatim(tmp_path: Path) -> None:
    """设置主屏 8 项逐字（默认值状态）。"""
    ctx = make_ctx(tmp_path, ["q"])
    assert run_settings_screen(ctx) == QUIT
    text = out(ctx)
    assert "=== 设置 ===" in text
    assert "配置文件：" in text and "settings.json" in text
    assert "  [1] 默认游戏版本       未设置" in text
    assert "  [2] 默认加载器         Fabric（fabric）" in text
    assert "  [3] 代理               未设置" in text
    assert "  [4] 颜色               auto（终端支持就用彩色）" in text
    assert "  [5] 并发数             6（上限 8）" in text
    assert "  [6] 缓存有效期         官方版本清单 24 小时 ｜ Modrinth 6 小时" in text
    assert "  [7] CurseForge API Key 未设置（本期未启用）" in text
    assert "  [8] 重置为默认设置" in text
    assert "  [q] 返回主菜单" in text


def test_set_default_mc_and_clear(tmp_path: Path) -> None:
    """[1] 手动输入版本号 / 清除。"""
    ctx = make_ctx(tmp_path, ["1", "26.3", "q"])
    run_settings_screen(ctx)
    assert "✓ 默认游戏版本已设为 26.3。" in out(ctx)
    assert ctx.settings.default_mc_version == "26.3"
    assert saved(ctx)["default_mc_version"] == "26.3"

    ctx2 = make_ctx(tmp_path, ["1", "c", "q"])
    run_settings_screen(ctx2)
    assert "✓ 已清除默认游戏版本。" in out(ctx2)
    assert ctx2.settings.default_mc_version is None
    assert saved(ctx2)["default_mc_version"] is None


def test_set_default_mc_invalid_shows_prd_error(tmp_path: Path) -> None:
    """[1] 非法版本号 -> PRD E07 文案，设置不变。"""
    ctx = make_ctx(tmp_path, ["1", "not-a-version", "q"])
    run_settings_screen(ctx)
    assert "✗ 无法识别的游戏版本：「not-a-version」" in out(ctx)
    assert ctx.settings.default_mc_version is None


def test_set_loader_and_clear(tmp_path: Path) -> None:
    """[2] 三种加载器 + 清除。"""
    ctx = make_ctx(tmp_path, ["2", "2", "q"])
    run_settings_screen(ctx)
    assert "✓ 默认加载器已设为 NeoForge。" in out(ctx)
    assert ctx.settings.default_loader is Loader.NEOFORGE
    assert saved(ctx)["default_loader"] == "neoforge"

    ctx2 = make_ctx(tmp_path, ["2", "c", "q"])
    run_settings_screen(ctx2)
    assert "✓ 默认加载器已恢复为 Fabric。" in out(ctx2)
    assert ctx2.settings.default_loader is Loader.FABRIC


def test_set_loader_invalid(tmp_path: Path) -> None:
    """[2] 非法选择就地重问。"""
    ctx = make_ctx(tmp_path, ["2", "9", "3", "q"])
    run_settings_screen(ctx)
    assert "✗ 无此选项，请重新选择。" in out(ctx)
    assert ctx.settings.default_loader is Loader.FORGE


def test_set_proxy_ok_clear_and_bad(tmp_path: Path) -> None:
    """[3] 代理：设置 / null 清除 / 非法拒绝。"""
    ctx = make_ctx(tmp_path, ["3", "http://127.0.0.1:7890", "q"])
    run_settings_screen(ctx)
    assert "✓ 代理已设为 http://127.0.0.1:7890。" in out(ctx)
    assert ctx.settings.proxy == "http://127.0.0.1:7890"
    assert saved(ctx)["proxy"] == "http://127.0.0.1:7890"

    ctx2 = make_ctx(tmp_path, ["3", "null", "q"])
    run_settings_screen(ctx2)
    assert "✓ 代理已清除。" in out(ctx2)
    assert saved(ctx2)["proxy"] is None

    ctx3 = make_ctx(tmp_path, ["3", "127.0.0.1:7890", "q"])
    run_settings_screen(ctx3)
    assert "✗「127.0.0.1:7890」不是有效的代理地址。正确格式如 http://127.0.0.1:7890。未做改动。" in out(ctx3)


def test_set_color(tmp_path: Path) -> None:
    """[4] 三种颜色模式。"""
    ctx = make_ctx(tmp_path, ["4", "3", "q"])
    run_settings_screen(ctx)
    assert "✓ 颜色已设为 never。" in out(ctx)
    assert ctx.settings.color == "never"
    assert saved(ctx)["color"] == "never"


def test_set_concurrency_ok_and_range(tmp_path: Path) -> None:
    """[5] 并发数：范围内通过，越界给逐字文案并重问。"""
    ctx = make_ctx(tmp_path, ["5", "12", "4", "q"])
    run_settings_screen(ctx)
    text = out(ctx)
    assert "✗ 并发数需在 1 到 8 之间（当前输入为 12）。未做改动。" in text
    assert "✓ 并发数已设为 4。" in text
    assert ctx.settings.concurrency == 4
    assert saved(ctx)["concurrency"] == 4


def test_set_concurrency_three_invalid_returns(tmp_path: Path) -> None:
    """[5] 连续 3 次非法 -> 回上一层。"""
    ctx = make_ctx(tmp_path, ["5", "0", "99", "x", "q"])
    run_settings_screen(ctx)
    assert "输入错误次数过多，返回上一级。" in out(ctx)
    assert ctx.settings.concurrency == 6


def test_set_cache_ttl_both_keys(tmp_path: Path) -> None:
    """[6] 两个缓存键分别改，互不影响。"""
    ctx = make_ctx(tmp_path, ["6", "1", "12", "6", "2", "3", "q"])
    run_settings_screen(ctx)
    assert ctx.settings.cache_ttl_hours["mojang"] == 12.0
    assert ctx.settings.cache_ttl_hours["api"] == 3.0
    assert saved(ctx)["cache_ttl_hours"] == {"mojang": 12.0, "api": 3.0}


def test_set_cache_ttl_range(tmp_path: Path) -> None:
    """[6] 越界提示范围。"""
    ctx = make_ctx(tmp_path, ["6", "2", "200", "q"])
    run_settings_screen(ctx)
    assert "✗ 缓存有效期需在 1 到 168 小时之间（当前输入为 200）。未做改动。" in out(ctx)


def test_set_curseforge_key_masked(tmp_path: Path) -> None:
    """[7] 保存后回显只显示后 4 位；null 清除。"""
    ctx = make_ctx(tmp_path, ["7", "abcd1234", "q"])
    run_settings_screen(ctx)
    text = out(ctx)
    assert "✓ CurseForge API Key 已保存（回显只显示后 4 位：****1234）。" in text
    assert ctx.settings.providers["curseforge"]["api_key"] == "abcd1234"
    assert saved(ctx)["providers"]["curseforge"]["api_key"] == "abcd1234"

    ctx2 = make_ctx(tmp_path, ["7", "null", "q"])
    run_settings_screen(ctx2)
    assert "✓ CurseForge API Key 已清除。" in out(ctx2)
    assert saved(ctx2)["providers"]["curseforge"]["api_key"] is None


def test_values_are_echoed_after_change(tmp_path: Path) -> None:
    """每项保存后立即回显新值（R3-A11 验收）。"""
    ctx = make_ctx(tmp_path, ["5", "3", "q", "q"])
    run_settings_screen(ctx)
    text = out(ctx)
    assert text.count("  [5] 并发数             3（上限 8）") == 1
    ctx2 = make_ctx(tmp_path, ["7", "abcd1234", "q", "q"])
    run_settings_screen(ctx2)
    assert "  [7] CurseForge API Key ****1234（本期未启用）" in out(ctx2)


def test_save_failure_keeps_memory_value(tmp_path: Path, monkeypatch) -> None:
    """写盘失败：给 PRD 那句 ✗，但本次运行仍然用新值（主 Agent 裁决）。"""
    ctx = make_ctx(tmp_path, ["5", "4", "q"])
    monkeypatch.setattr("modcheck.cli.screens_settings.save_settings",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")))
    run_settings_screen(ctx)
    text = out(ctx)
    assert "✗ 设置无法保存到" in text and "本次修改仅在当前运行期间有效。" in text
    assert ctx.settings.concurrency == 4
    assert not ctx.settings_path.exists()


# ---------------------------------------------------------------- R3-A12 重置设置
def test_reset_confirm_screen_verbatim(tmp_path: Path) -> None:
    """确认屏逐字列出 7 项影响面 + 明确清单与缓存不受影响。"""
    ctx = make_ctx(tmp_path, ["8", "n", "q"])
    run_settings_screen(ctx)
    text = out(ctx)
    assert "⚠ 即将把设置恢复成出厂状态：" in text
    assert "   默认游戏版本、默认加载器、代理、颜色、并发数、缓存有效期、CurseForge API Key 都会回到初始值。" in text
    assert "   （模组清单和下载缓存不会被删除。）" in text
    assert "确认重置？(y/N) > " not in text      # 注入 input_fn 时提示不进 console 流
    assert "✓ 设置已重置为默认值。" not in text


def test_reset_no_keeps_file_bytes(tmp_path: Path) -> None:
    """答 n（或直接回车）：settings.json 一个字节都不变。"""
    ctx = make_ctx(tmp_path, ["5", "2", "q"])
    run_settings_screen(ctx)
    path = ctx.settings_path
    before = path.read_bytes()
    ctx2 = make_ctx(tmp_path, ["8", "n", "q"])
    ctx2.settings = ctx.settings
    run_settings_screen(ctx2)
    assert path.read_bytes() == before

    ctx3 = make_ctx(tmp_path, ["8", "", "q"])
    ctx3.settings = ctx.settings
    run_settings_screen(ctx3)
    assert path.read_bytes() == before


def test_reset_yes_restores_defaults(tmp_path: Path) -> None:
    """答 y：所有值回默认，settings.json 与 config show 一致。"""
    from fakes import FakeProvider
    from modcheck.cli.commands.misc import run_config
    from modcheck.providers.registry import ProviderRegistry

    ctx = make_ctx(tmp_path, ["5", "2", "4", "never", "3", "http://127.0.0.1:7890",
                              "7", "abcd1234", "q"])
    run_settings_screen(ctx)
    assert ctx.settings.concurrency == 2 and ctx.settings.color == "never"
    ctx2 = make_ctx(tmp_path, ["8", "y", "q"])
    ctx2.settings = ctx.settings
    run_settings_screen(ctx2)
    assert "✓ 设置已重置为默认值。" in out(ctx2)
    assert ctx2.settings.to_dict() == Settings().to_dict()
    assert saved(ctx2) == Settings().to_dict()

    ctx2.registry = ProviderRegistry(providers=[FakeProvider()])
    ctx2.console.stream.truncate(0)            # type: ignore[attr-defined]
    ctx2.console.stream.seek(0)                # type: ignore[attr-defined]
    run_config(Namespace(action="show", key=None, value=None), ctx2)
    text = out(ctx2)
    assert "未设置" in text and "6（上限 8" in text and "auto" in text


def test_every_item_has_back_path(tmp_path: Path) -> None:
    """7 个子项都要能用 b 返回（R3-A11 验收：每项都有 [b]）。"""
    for key in ("1", "2", "3", "4", "5", "6", "7"):
        ctx = make_ctx(tmp_path, [key, "b", "q"])
        assert run_settings_screen(ctx) == QUIT
        assert ctx.settings.to_dict() == Settings().to_dict(), key


def test_back_at_main_screen_returns_quit(tmp_path: Path) -> None:
    """设置主屏按 b 也回主菜单（没有死胡同）。"""
    ctx = make_ctx(tmp_path, ["b"])
    assert run_settings_screen(ctx) == QUIT


def test_invalid_main_choice_three_times(tmp_path: Path) -> None:
    """设置屏非法输入 3 次 -> 回主菜单。"""
    ctx = make_ctx(tmp_path, ["!@#", "!@#", "!@#", "q"])
    assert run_settings_screen(ctx) == QUIT
    assert "输入错误次数过多，返回上一级。" in out(ctx)


def test_config_show_reflects_changes(tmp_path: Path) -> None:
    """改完设置后 config show 与 settings.json 同步（R3-A11 验收）。"""
    from fakes import FakeProvider
    from modcheck.cli.commands.misc import run_config
    from modcheck.providers.registry import ProviderRegistry

    ctx = make_ctx(tmp_path, ["5", "2", "q"])
    run_settings_screen(ctx)
    ctx.registry = ProviderRegistry(providers=[FakeProvider()])
    ctx.console.stream.truncate(0)            # type: ignore[attr-defined]
    ctx.console.stream.seek(0)                # type: ignore[attr-defined]
    run_config(Namespace(action="show", key=None, value=None), ctx)
    text = out(ctx)
    assert "并发数" in text and "2（上限 8" in text
    assert saved(ctx)["concurrency"] == 2
