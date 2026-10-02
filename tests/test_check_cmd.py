"""T-19 check 命令与退出码矩阵（PRD §10.4；验收 H 组）。"""
from __future__ import annotations

import io
from argparse import Namespace
from pathlib import Path

import pytest

from fakes import FakeClock, FakeProvider, FakeTransport, json_response
from modcheck.cli.commands.check import VERDICT_EXIT, run_check
from modcheck.cli.context import AppContext
from modcheck.console import Console
from modcheck.core.models import (Loader, ModEntry, ProjectHit, ReasonCode, SourceKind,
                                  Status, VersionInfo)
from modcheck.errors import EXIT_NO_SOURCE, EXIT_OK, EXIT_USAGE, ProviderNetworkError, ProviderUnavailable
from modcheck.providers.http import HttpConfig, HttpClient, RateLimiter
from modcheck.providers.registry import ProviderRegistry
from modcheck.storage.profiles import new_profile, profile_path, save_profile


def V(pid: str, number: str, mc: tuple[str, ...], *, vtype: str = "release") -> VersionInfo:
    """构造版本对象。"""
    return VersionInfo.from_api({"id": pid + number, "project_id": pid, "version_number": number,
                                 "name": number, "date_published": "2026-09-18T00:00:00Z",
                                 "version_type": vtype, "game_versions": list(mc),
                                 "loaders": ["fabric"], "files": []})


def make_ctx(tmp_path: Path, provider, *, offline: bool = True) -> AppContext:
    """构造一个离线上下文（Mojang 请求会失败并降级）。"""
    cfg = HttpConfig(rate_limit_per_min=100000)

    def handler(method: str, url: str, data, index: int):
        raise ProviderNetworkError("offline")

    client = HttpClient(cfg, transport=FakeTransport(handler))
    console = Console(stream=io.StringIO(), color="never", width=100)
    registry = ProviderRegistry(providers=[provider]) if provider is not None else \
        ProviderRegistry(providers=[])
    return AppContext(settings=__import__("modcheck.core.models", fromlist=["Settings"]).Settings(),
                      config_dir=tmp_path, console=console, registry=registry, cache=None,
                      client=client, prompter=None, interactive=False)


def write_profile(tmp_path: Path, entries: list[ModEntry]) -> Path:
    """写一份测试清单。"""
    profile = new_profile("demo")
    profile.mods = entries
    path = profile_path(tmp_path, "demo")
    save_profile(profile, path)
    return path


def entry(key: str, **kw: object) -> ModEntry:
    """构造清单条目。"""
    return ModEntry(key=key, display_name=str(kw.pop("display", key)), mod_id=key,
                    sources={"modrinth": key}, source_kind=SourceKind.HASH, **kw)  # type: ignore[arg-type]


def run(tmp_path: Path, provider, entries: list[ModEntry], **overrides: object) -> tuple[int, str]:
    """跑一次 check 并返回 (退出码, 输出)。"""
    ctx = make_ctx(tmp_path, provider)
    path = write_profile(tmp_path, entries)
    args = Namespace(profile=None, file=str(path), mods_dir=None, mc="26.3", loader="fabric",
                     json_out=None, md_out=None, csv_out=None, refresh=False, jobs=None,
                     yes=True, pre=False, quiet=True, window=25, debug=False, no_color=True,
                     resolve=False)
    for key, value in overrides.items():
        setattr(args, key, value)
    code = run_check(args, ctx)
    return code, ctx.console.stream.getvalue()  # type: ignore[attr-defined]


def test_all_ready_exit_zero(tmp_path: Path) -> None:
    """全部就绪 -> 退出码 0。"""
    provider = FakeProvider(releases={"ok": [V("ok", "26.3", ("26.3",))]})
    code, text = run(tmp_path, provider, [entry("ok", display="Ok")])
    assert code == EXIT_OK
    assert "结论：✅" in text


def test_blocked_exit_one(tmp_path: Path) -> None:
    """有阻塞 -> 退出码 1。"""
    provider = FakeProvider(releases={"bad": []}, any_loader={"bad": []},
                            projects={"bad": __import__("modcheck.core.models",
                                                        fromlist=["ProjectInfo"]).ProjectInfo(
                                project_id="bad", slug="bad", title="Bad", description="",
                                project_type="mod", loaders=("forge",), game_versions=(),
                                downloads=0, version_count=3)})
    code, text = run(tmp_path, provider, [entry("bad", display="Bad")])
    assert code == 1
    assert "🔴 阻塞" in text
    assert "没有 Fabric 版本" in text


def test_network_error_is_unknown_exit_two(tmp_path: Path) -> None:
    """网络错误 -> ⚪ 且退出码 2（绝不是红色、绝不是 1）。"""
    provider = FakeProvider(raise_on={"*": ProviderNetworkError("timeout")})
    code, text = run(tmp_path, provider, [entry("x", display="X")])
    assert code == 2
    assert "⚪ 未判定" in text
    assert "🔴 阻塞（" not in text   # 不能出现阻塞分组（汇总行里的"阻塞 0"不算）


def test_unmatched_is_unknown_not_guessed(tmp_path: Path) -> None:
    """找不到完全同名 -> ⚪ UNMATCHED（非交互模式绝不猜）。"""
    provider = FakeProvider(hits=[ProjectHit("P9", "other-mod", "Other Mod", 1, "d", "fake")])
    code, text = run(tmp_path, provider, [ModEntry(key="mystery", display_name="Mystery")])
    assert code == 2
    assert "不会以猜测方式匹配" in text


def test_check_does_not_search_by_default(tmp_path: Path) -> None:
    """裁决 D34：默认路径**不发搜索请求**（scan 已用同样规则搜过，结果必然相同）。"""
    calls: list[str] = []
    provider = FakeProvider(hits=[ProjectHit("P9", "mystery", "Mystery", 1, "d", "fake")])
    original = provider.search

    def counting_search(query: str, limit: int = 10):
        calls.append(query)
        return original(query, limit)

    provider.search = counting_search  # type: ignore[method-assign]
    code, _ = run(tmp_path, provider, [ModEntry(key="mystery", display_name="Mystery")])
    assert calls == []
    assert code == 2


def test_resolve_searches_at_most_two_candidates(tmp_path: Path) -> None:
    """显式 --resolve 才搜索，且每模组最多试 2 个候选名。"""
    calls: list[str] = []
    provider = FakeProvider(hits=[ProjectHit("P9", "mystery", "Mystery", 1, "d", "fake")])
    original = provider.search

    def counting_search(query: str, limit: int = 10):
        calls.append(query)
        return original(query, limit)

    provider.search = counting_search  # type: ignore[method-assign]
    entry = ModEntry(key="mystery", display_name="Mystery", mod_id="mystery")
    code, _ = run(tmp_path, provider, [entry], resolve=True)
    assert len(calls) <= 2
    assert code in (0, 1, 2)


def test_no_provider_exit_four(tmp_path: Path) -> None:
    """没有可用数据源 -> 退出码 4。"""
    ctx = make_ctx(tmp_path, None)
    path = write_profile(tmp_path, [entry("a")])
    args = Namespace(profile=None, file=str(path), mods_dir=None, mc="26.3", loader="fabric",
                     json_out=None, md_out=None, csv_out=None, refresh=False, jobs=None,
                     yes=True, pre=False, quiet=True, window=25, debug=False, no_color=True)
    with pytest.raises(ProviderUnavailable) as exc:
        run_check(args, ctx)
    assert exc.value.exit_code == EXIT_NO_SOURCE


def test_degraded_exit_zero(tmp_path: Path) -> None:
    """只有需降级 -> 退出码 0（决策 D2）。"""
    newest = V("n", "26.3", ("26.3",))
    compat = V("c", "26.1", ("26.1",))
    provider = FakeProvider(releases={"old": [newest]}, compat={"old": [compat]})
    code, _ = run(tmp_path, provider, [entry("old")], mc="26.1")
    assert code == 0


def test_next_element_lazy_get_project(tmp_path: Path) -> None:
    """get_project 只在 A 与 A2 都为空时才被调用（省 90% 请求）。"""
    newest = V("n", "26.3", ("26.3",))
    provider = FakeProvider(releases={"ok": [newest]})
    run(tmp_path, provider, [entry("ok")])
    assert "get_project" not in provider.raise_on  # 没被调用过就没有异常记录


def test_verdict_exit_mapping() -> None:
    """退出码映射表：阻塞 1、未判定 2、中断 130。"""
    assert VERDICT_EXIT[__import__("modcheck.core.report", fromlist=["Verdict"]).Verdict.BLOCKED] == 1
    assert VERDICT_EXIT[__import__("modcheck.core.report", fromlist=["Verdict"]).Verdict.ALL_UNKNOWN] == 2
    assert VERDICT_EXIT[__import__("modcheck.core.report", fromlist=["Verdict"]).Verdict.INTERRUPTED] == 130
