"""PRD §5.7：交互里选 q = 结束检查（退出码 130），**不是**把那个模组标成 ⚪。

R4 复核裁决（第 5 条）：check_one 的兜底 except Exception 曾把 UserCancelled 一起吞掉，
于是"用户取消"变成了"这个模组未判定"，检查还会继续跑完剩下的模组。
本文件同时守住两条边界：
  * 用户主动取消 -> 原样上抛（本轮修复）；
  * 普通异常 -> 仍然吞掉并标 ⚪（S4：单个模组失败绝不中断整体检查）。
"""
from __future__ import annotations

import io
from argparse import Namespace
from pathlib import Path

import pytest

from fakes import FakeProvider, FakeTransport
from modcheck.cli.commands.check import run_check
from modcheck.cli.context import AppContext
from modcheck.cli.prompts import Prompter
from modcheck.console import Console
from modcheck.core.checker_run import check_all, check_one
from modcheck.core.models import Loader, ModEntry, ProjectHit, ReasonCode, Settings, Status
from modcheck.errors import ProviderNetworkError, UserCancelled
from modcheck.flows.check_flow import run_check_flow
from modcheck.providers.http import HttpConfig, HttpClient
from modcheck.providers.registry import ProviderRegistry
from modcheck.storage.profiles import load_profile, new_profile, profile_path, save_profile


def make_provider() -> FakeProvider:
    """能搜到 mystery 的假数据源。"""
    return FakeProvider(hits=[ProjectHit("P9", "mystery", "Mystery", 1, "d", "fake")])


def unmatched(index: int = 0) -> ModEntry:
    """没有平台标识的条目 -> 会走交互匹配回调。"""
    return ModEntry(key="m%d" % index, display_name="Mystery %d" % index,
                    mod_id="mystery", sources={"modrinth": None})


def cancel_matcher(seen: list[str]):
    """一被问到就"选 q"的回调（等价于用户在交互里按 q）。"""
    def matcher(entry: ModEntry, hits) -> None:
        seen.append(entry.key)
        raise UserCancelled("bye")
    return matcher


def make_ctx(tmp_path: Path, provider, *, prompter=None, interactive: bool = False) -> AppContext:
    """最小离线上下文。"""
    def handler(method: str, url: str, data, index: int):
        raise ProviderNetworkError("offline")

    client = HttpClient(HttpConfig(rate_limit_per_min=100000),
                        transport=FakeTransport(handler))
    return AppContext(settings=Settings(), config_dir=tmp_path,
                      console=Console(stream=io.StringIO(), color="never", width=100),
                      registry=ProviderRegistry(providers=[provider]), cache=None,
                      client=client, prompter=prompter, interactive=interactive)


def write_profile(tmp_path: Path, entries: list[ModEntry]) -> Path:
    """写一份只有这几条模组的清单。"""
    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)
    profile = new_profile("demo")
    profile.mods = entries
    path = profile_path(tmp_path / "profiles", "demo")
    save_profile(profile, path)
    return path


def check_args(**over: object) -> Namespace:
    """一份完整的 check 参数。"""
    base: dict[str, object] = dict(
        profile=None, file=None, mods_dir=None, mc="26.3", loader="fabric",
        json_out=None, md_out=None, csv_out=None, refresh=False, jobs=1,
        yes=True, pre=False, quiet=True, window=25, debug=False, no_color=True,
        resolve=False)
    base.update(over)
    return Namespace(**base)


# ---------------------------------------------------------------- core 层
def test_check_one_reraises_user_cancelled() -> None:
    """选 q == 用户主动取消：check_one 必须原样上抛，绝不降级成 ⚪。"""
    seen: list[str] = []
    with pytest.raises(UserCancelled):
        check_one(unmatched(), make_provider(), loader=Loader.FABRIC, mc_version="26.3",
                  interactive_match=cancel_matcher(seen))
    assert seen == ["m0"]


def test_check_one_still_swallows_ordinary_errors() -> None:
    """S4 不能被破坏：普通异常仍然吞掉并标 ⚪（单个模组失败不中断整体检查）。"""
    class Boom(FakeProvider):
        """查询时抛普通异常。"""

        def releases_for_loader(self, project_id, loader, *, window=25, prerelease=False):
            raise RuntimeError("boom")

    entry = ModEntry(key="x", display_name="X", mod_id="x", sources={"modrinth": "x"})
    item = check_one(entry, Boom(), loader=Loader.FABRIC, mc_version="26.3")
    assert item.status is Status.UNKNOWN
    assert item.reason is ReasonCode.ERROR
    assert "RuntimeError" in item.provider_message


def test_check_all_stops_at_first_user_cancel() -> None:
    """选 q 之后不再问后面的模组（顺序路径立刻中断）。"""
    seen: list[str] = []
    entries = [unmatched(i) for i in range(5)]
    with pytest.raises(UserCancelled):
        check_all(entries, make_provider(), loader=Loader.FABRIC, mc_version="26.3", jobs=1,
                  interactive_match=cancel_matcher(seen))
    assert seen == ["m0"]


def test_check_all_pool_path_propagates_user_cancel() -> None:
    """并发路径（jobs>1）同样要把取消上抛，而不是产出一堆 ⚪。"""
    seen: list[str] = []
    entries = [unmatched(i) for i in range(3)]
    with pytest.raises(UserCancelled):
        check_all(entries, make_provider(), loader=Loader.FABRIC, mc_version="26.3", jobs=3,
                  interactive_match=cancel_matcher(seen))
    assert seen, "至少要问过一次"


# ---------------------------------------------------------------- 流程层
def test_flow_returns_interrupted_outcome_not_unknown() -> None:
    """流程层拿到取消 -> interrupted 报告；那个模组不会被记成 ⚪。"""
    seen: list[str] = []
    outcome = run_check_flow([unmatched(), unmatched(1)], provider=make_provider(),
                             loader=Loader.FABRIC, mc_version="26.3", jobs=1,
                             interactive_match=cancel_matcher(seen), profile_name="demo")
    report = outcome.report
    assert report.interrupted is True
    assert report.completed == 0
    assert report.total == 2
    assert report.summary["unknown"] == 0            # 不是"未判定"
    assert report.verdict().value == "interrupted"


# ---------------------------------------------------------------- CLI 层
def test_cli_interactive_quit_returns_130(tmp_path: Path) -> None:
    """端到端：交互里选 q -> 退出码 130，横幅说"按你的要求"，且不出现 ⚪ / 内部错误。"""
    console = Console(stream=io.StringIO(), color="never", width=100)
    prompter = Prompter(input_fn=lambda prompt: "q", out=console)
    ctx = make_ctx(tmp_path, make_provider(), prompter=prompter, interactive=True)
    ctx.console = console  # type: ignore[assignment]
    path = write_profile(tmp_path, [unmatched()])

    code = run_check(check_args(file=str(path)), ctx)
    out = console.stream.getvalue()  # type: ignore[attr-defined]

    assert code == 130
    assert out.count("结论：") == 1
    assert "已按用户要求结束检查" in out       # 用户按的是 q，就照实说是他结束的
    assert "按了 Ctrl+C" not in out           # 绝不能对用户说假话
    assert "⚪ 未判定（" not in out          # 不能把"用户取消"记成"这个模组查不到"
    assert "程序内部出错" not in out         # 更不能变成"本不应该发生"的内部错误
    saved = load_profile(path)               # 取消不做任何写盘：条目保持原样
    assert saved.mods[0].sources.get("modrinth") is None


def test_cli_keyboard_interrupt_keeps_ctrl_c_wording(tmp_path: Path) -> None:
    """对照组：真的按了 Ctrl+C 时，横幅仍然是"按了 Ctrl+C"（两种原因各说各的）。"""
    class Interrupted(FakeProvider):
        """查询时抛 KeyboardInterrupt（等价于用户按了 Ctrl+C）。"""

        def releases_for_loader(self, project_id, loader, *, window=25, prerelease=False):
            raise KeyboardInterrupt()

    entry = ModEntry(key="x", display_name="X", mod_id="x", sources={"modrinth": "x"})
    console = Console(stream=io.StringIO(), color="never", width=100)
    ctx = make_ctx(tmp_path, Interrupted())
    ctx.console = console  # type: ignore[assignment]
    path = write_profile(tmp_path, [entry])

    code = run_check(check_args(file=str(path)), ctx)
    out = console.stream.getvalue()  # type: ignore[attr-defined]

    assert code == 130
    assert "已中断（用户按下 Ctrl+C）" in out
    assert "已按用户要求结束检查" not in out


def test_cli_ordinary_failure_still_renders_unknown(tmp_path: Path) -> None:
    """对照组：普通异常（不是取消）仍然走 ⚪ + 退出码 2，S4 语义不变。"""
    class Boom(FakeProvider):
        """查询直接抛普通异常。"""

        def releases_for_loader(self, project_id, loader, *, window=25, prerelease=False):
            raise RuntimeError("boom")

    entry = ModEntry(key="x", display_name="X", mod_id="x", sources={"modrinth": "x"})
    console = Console(stream=io.StringIO(), color="never", width=100)
    ctx = make_ctx(tmp_path, Boom())
    ctx.console = console  # type: ignore[assignment]
    path = write_profile(tmp_path, [entry])

    code = run_check(check_args(file=str(path)), ctx)
    out = console.stream.getvalue()  # type: ignore[attr-defined]
    assert code == 2
    assert "⚪ 未判定（" in out
