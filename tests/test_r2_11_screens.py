"""R2-11：交互式检查的三屏 + 确认页（PRD §5.6）。"""
from __future__ import annotations

import io
from argparse import Namespace
from pathlib import Path

from fakes import FakeProvider
from modcheck.cli.context import AppContext
from modcheck.cli.menu import _screen_confirm, _screen_loader, _screen_version
from modcheck.cli.prompts import Prompter
from modcheck.console import Console
from modcheck.core.models import Loader, ModEntry, Settings
from modcheck.errors import ProviderNetworkError
from modcheck.providers.http import HttpConfig, HttpClient
from modcheck.providers.registry import ProviderRegistry
from fakes import FakeTransport


def feed(values: list[str]):
    """注入输入序列。"""
    queue = list(values)
    return lambda _prompt="": queue.pop(0) if queue else "q"


def make_ctx(tmp_path: Path) -> AppContext:
    """离线上下文（Mojang 清单拉不到 -> 走手动输入分支）。"""
    def handler(method: str, url: str, data, index: int):
        raise ProviderNetworkError("offline")

    client = HttpClient(HttpConfig(rate_limit_per_min=100000), transport=FakeTransport(handler))
    return AppContext(settings=Settings(), config_dir=tmp_path,
                      console=Console(stream=io.StringIO(), color="never", width=100),
                      registry=ProviderRegistry(providers=[FakeProvider()]), cache=None,
                      client=client, prompter=None, interactive=True)


def online_ctx(tmp_path: Path) -> AppContext:
    """能取到官方版本清单的上下文（用夹具里的裁剪版 manifest）。"""
    from conftest import load_fixture
    from fakes import json_response

    def handler(method: str, url: str, data, index: int):
        return json_response(load_fixture("manifest_v2.json"))

    client = HttpClient(HttpConfig(rate_limit_per_min=100000), transport=FakeTransport(handler))
    return AppContext(settings=Settings(), config_dir=tmp_path,
                      console=Console(stream=io.StringIO(), color="never", width=100),
                      registry=ProviderRegistry(providers=[FakeProvider()]), cache=None,
                      client=client, prompter=None, interactive=True)


def test_version_screen_numbers_and_picks(tmp_path: Path) -> None:
    """屏②：列出最近正式版，编号选择写入 args.mc。"""
    ctx = online_ctx(tmp_path)
    args = Namespace(mc=None)
    assert _screen_version(args, ctx, Prompter(input_fn=feed(["2"]), out=ctx.console)) is True
    out = ctx.console.stream.getvalue()  # type: ignore[attr-defined]
    assert "请选择目标游戏版本（最近 10 个官方正式版）：" in out
    assert "（最新正式版）" in out
    assert "[m] 手动输入版本号" in out
    assert args.mc == "26.2"          # 夹具里第 2 个正式版


def test_version_screen_back_returns_false(tmp_path: Path) -> None:
    """屏②：b 返回上一步。"""
    ctx = make_ctx(tmp_path)
    args = Namespace(mc=None)
    assert _screen_version(args, ctx, Prompter(input_fn=feed(["b"]), out=ctx.console)) is False


def test_version_screen_manual_fallback(tmp_path: Path) -> None:
    """屏②：官方清单取不到时，允许手动输入（PRD §7.1 第 10 条）。"""
    ctx = make_ctx(tmp_path)
    args = Namespace(mc=None)
    assert _screen_version(args, ctx, Prompter(input_fn=feed(["26.1.2"]), out=ctx.console)) is True
    assert args.mc == "26.1.2"


def test_loader_screen_all_options(tmp_path: Path) -> None:
    """屏③：1/2/3 选加载器，d 用默认，b 返回。"""
    ctx = make_ctx(tmp_path)
    for raw, expected in (("1", Loader.FABRIC), ("2", Loader.NEOFORGE), ("3", Loader.FORGE)):
        args = Namespace(loader=None)
        assert _screen_loader(args, ctx, Prompter(input_fn=feed([raw]), out=ctx.console)) is True
        assert args.loader == expected.value
    ctx.settings.default_loader = Loader.NEOFORGE
    args = Namespace(loader=None)
    assert _screen_loader(args, ctx, Prompter(input_fn=feed(["d"]), out=ctx.console)) is True
    assert args.loader == "neoforge"
    args = Namespace(loader=None)
    assert _screen_loader(args, ctx, Prompter(input_fn=feed(["b"]), out=ctx.console)) is False


def test_confirm_screen_shows_cost_and_can_abort(tmp_path: Path) -> None:
    """屏④：确认页必须给出模组数 / 预计请求数 / 预计用时，且能取消。"""
    ctx = make_ctx(tmp_path)
    args = Namespace(profile="服务器A", mc="26.3", loader="fabric")
    ok = _screen_confirm(args, ctx, Prompter(input_fn=feed(["n"]), out=ctx.console), 120)
    out = ctx.console.stream.getvalue()  # type: ignore[attr-defined]
    assert ok is False
    assert "即将检查：" in out
    assert "服务器A（120 个模组）" in out
    assert "Minecraft 26.3" in out
    assert "Fabric" in out
    assert "预计请求：约 240 次" in out
    assert "预计用时" in out


def test_confirm_screen_accepts_default_yes(tmp_path: Path) -> None:
    """回车 = 默认继续。"""
    ctx = make_ctx(tmp_path)
    args = Namespace(profile="p", mc="26.3", loader="fabric")
    assert _screen_confirm(args, ctx, Prompter(input_fn=feed([""]), out=ctx.console), 5) is True
