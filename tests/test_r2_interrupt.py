"""中断路径回归（主 Agent 实测：中断后会打印错误的第二结论）。

症状：Ctrl+C 后除了「检查被中断」还多打一条「清单中没有任何模组」，
并建议用户去重扫 mods 文件夹 —— 可能覆盖手工编辑过的清单。
"""
from __future__ import annotations

import io
from argparse import Namespace
from pathlib import Path

from fakes import FakeProvider
from modcheck.cli.commands.check import run_check
from modcheck.cli.context import AppContext
from modcheck.console import Console
from modcheck.core.models import ModEntry, Settings
from modcheck.providers.registry import ProviderRegistry
from modcheck.storage.profiles import new_profile, profile_path, save_profile


def make_ctx(tmp_path: Path, provider: FakeProvider) -> AppContext:
    """最小上下文（不走网络）。"""
    from fakes import FakeTransport
    from modcheck.errors import ProviderNetworkError
    from modcheck.providers.http import HttpConfig, HttpClient

    def handler(method: str, url: str, data, index: int):
        raise ProviderNetworkError("offline")

    client = HttpClient(HttpConfig(rate_limit_per_min=100000),
                        transport=FakeTransport(handler))
    return AppContext(settings=Settings(), config_dir=tmp_path,
                      console=Console(stream=io.StringIO(), color="never", width=100),
                      registry=ProviderRegistry(providers=[provider]), cache=None,
                      client=client, prompter=None, interactive=False)


def write_profile(tmp_path: Path, count: int = 30) -> Path:
    """写一份有 count 个模组的清单。"""
    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)
    profile = new_profile("s")
    profile.mods = [ModEntry(key="m" + str(i), display_name="M" + str(i), mod_id="m" + str(i),
                             sources={"modrinth": "m" + str(i)}) for i in range(count)]
    path = profile_path(tmp_path / "profiles", "s")
    save_profile(profile, path)
    return path


def run(tmp_path: Path, provider: FakeProvider) -> tuple[int, str]:
    """跑一次 check。"""
    ctx = make_ctx(tmp_path, provider)
    path = write_profile(tmp_path)
    args = Namespace(profile=None, file=str(path), mods_dir=None, mc="26.3", loader="fabric",
                     json_out=None, md_out=None, csv_out=None, refresh=False, jobs=1,
                     yes=True, pre=False, quiet=True, window=25, debug=False, no_color=True,
                     resolve=False)
    code = run_check(args, ctx)
    return code, ctx.console.stream.getvalue()  # type: ignore[attr-defined]


def test_keyboard_interrupt_returns_130(tmp_path: Path) -> None:
    """中断 -> 退出码 130，且绝不打印 traceback。"""
    provider = FakeProvider(raise_on={"releases_for_loader": KeyboardInterrupt()})
    code, out = run(tmp_path, provider)
    assert code == 130
    assert "Traceback" not in out


def test_interrupt_prints_exactly_one_verdict(tmp_path: Path) -> None:
    """中断后**只允许一条结论行**（修复前会多打一条错误的空清单结论）。"""
    provider = FakeProvider(raise_on={"releases_for_loader": KeyboardInterrupt()})
    _, out = run(tmp_path, provider)
    assert out.count("结论：") == 1, out[-600:]
    assert "没有任何模组" not in out
    assert "扫描 mods 文件夹" not in out


def test_interrupt_summary_mentions_incomplete(tmp_path: Path) -> None:
    """中断摘要必须说明"结果不完整"。"""
    provider = FakeProvider(raise_on={"releases_for_loader": KeyboardInterrupt()})
    _, out = run(tmp_path, provider)
    assert "结果不完整" in out


def test_empty_profile_prints_one_verdict(tmp_path: Path) -> None:
    """D-22：真正的空清单也只能有一条结论行，并给出扫描引导。"""
    provider = FakeProvider()
    ctx = make_ctx(tmp_path, provider)
    path = write_profile(tmp_path, count=0)
    args = Namespace(profile=None, file=str(path), mods_dir=None, mc="26.3", loader="fabric",
                     json_out=None, md_out=None, csv_out=None, refresh=False, jobs=1,
                     yes=True, pre=False, quiet=True, window=25, debug=False, no_color=True,
                     resolve=False)
    code = run_check(args, ctx)
    out = ctx.console.stream.getvalue()  # type: ignore[attr-defined]
    assert code == 0
    assert out.count("结论：") == 1, out[-600:]
    # 空清单：结论本身必须说清楚，且不再有「下一步」段落（用户要求去掉常识性提示）
    assert "没有任何模组" in out
    assert "下一步" not in out
