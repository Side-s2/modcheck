"""R2-09：数据源整体不可用 -> 退出码 4（E01）。

before 基线（主 Agent 实测）：代理不可用时 exit=2，PRD 要求 4。
"""
from __future__ import annotations

import io
from argparse import Namespace
from pathlib import Path

from fakes import FakeClock, FakeTransport
from modcheck.cli.commands.check import run_check
from modcheck.cli.context import AppContext
from modcheck.console import Console
from modcheck.core.models import ModEntry, Settings, SourceKind
from modcheck.errors import EXIT_NO_SOURCE, ProviderNetworkError
from modcheck.providers.http import HttpConfig, HttpClient
from modcheck.providers.modrinth import ModrinthProvider
from modcheck.providers.registry import ProviderRegistry
from modcheck.storage.profiles import new_profile, profile_path, save_profile


def broken_ctx(tmp_path: Path) -> AppContext:
    """真实 Modrinth Provider + 永远连不上的 transport（模拟代理坏了）。"""
    def handler(method: str, url: str, data, index: int):
        raise ProviderNetworkError("connection refused")

    clock = FakeClock()
    client = HttpClient(HttpConfig(rate_limit_per_min=100000, retries=0),
                        transport=FakeTransport(handler))
    return AppContext(settings=Settings(), config_dir=tmp_path,
                      console=Console(stream=io.StringIO(), color="never", width=100),
                      registry=ProviderRegistry(providers=[ModrinthProvider(client)]),
                      cache=None, client=client, prompter=None, interactive=False)


def write_profile(tmp_path: Path) -> Path:
    """写一份只有一个模组的清单。"""
    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)
    profile = new_profile("demo")
    profile.mods = [ModEntry(key="carpet", display_name="Carpet", mod_id="carpet",
                             sources={"modrinth": "carpet"}, source_kind=SourceKind.HASH)]
    path = profile_path(tmp_path / "profiles", "demo")
    save_profile(profile, path)
    return path


def test_unavailable_source_returns_4(tmp_path: Path) -> None:
    """所有请求都失败且无一成功 -> 退出码 4 + E01 文案。"""
    ctx = broken_ctx(tmp_path)
    path = write_profile(tmp_path)
    args = Namespace(profile=None, file=str(path), mods_dir=None, mc="26.3", loader="fabric",
                     json_out=None, md_out=None, csv_out=None, refresh=False, jobs=None,
                     yes=True, pre=False, quiet=True, window=25, debug=False, no_color=True,
                     resolve=False)
    code = run_check(args, ctx)
    out = ctx.console.stream.getvalue()  # type: ignore[attr-defined]
    assert code == EXIT_NO_SOURCE, out[-400:]
    assert "无法连接 Modrinth" in out
    assert "config set proxy" in out


def test_partial_failure_is_not_exit_4(tmp_path: Path) -> None:
    """有成功请求时不能判成数据源不可用（正常结束，退出码按结论）。"""
    from fakes import json_response

    def handler(method: str, url: str, data, index: int):
        if "version_manifest" in url:
            raise ProviderNetworkError("offline")
        return json_response([{"id": "V1", "project_id": "carpet", "version_number": "26.3",
                               "name": "26.3", "date_published": "2026-09-18T00:00:00Z",
                               "version_type": "release", "game_versions": ["26.3"],
                               "loaders": ["fabric"], "files": []}])

    clock = FakeClock()
    client = HttpClient(HttpConfig(rate_limit_per_min=100000, retries=0),
                        transport=FakeTransport(handler))
    ctx = AppContext(settings=Settings(), config_dir=tmp_path,
                     console=Console(stream=io.StringIO(), color="never", width=100),
                     registry=ProviderRegistry(providers=[ModrinthProvider(client)]),
                     cache=None, client=client, prompter=None, interactive=False)
    path = write_profile(tmp_path)
    args = Namespace(profile=None, file=str(path), mods_dir=None, mc="26.3", loader="fabric",
                     json_out=None, md_out=None, csv_out=None, refresh=False, jobs=None,
                     yes=True, pre=False, quiet=True, window=25, debug=False, no_color=True,
                     resolve=False)
    code = run_check(args, ctx)
    assert code != EXIT_NO_SOURCE
    assert code == 0
