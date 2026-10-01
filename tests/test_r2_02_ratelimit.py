"""R2-02 收尾：限流要显式告知用户 + 首窗不得突发。"""
from __future__ import annotations

import io
from argparse import Namespace
from pathlib import Path

from fakes import FakeClock, FakeProvider, FakeTransport
from modcheck.cli.commands.check import run_check
from modcheck.cli.context import AppContext
from modcheck.console import Console
from modcheck.core.models import ModEntry, ReasonCode, Settings, Status
from modcheck.errors import ProviderNetworkError
from modcheck.providers.http import HttpConfig, HttpClient, RateLimiter
from modcheck.providers.registry import ProviderRegistry
from modcheck.storage.profiles import new_profile, profile_path, save_profile


def rate_limited_client(retries: int = 0) -> HttpClient:
    """transport 永远返回 429 —— 真实地触发客户端的限流计数。"""
    from modcheck.providers.http import HttpResponse

    def handler(method: str, url: str, data, index: int):
        return HttpResponse(status=429, headers={"Retry-After": "0"}, body=b"")

    return HttpClient(HttpConfig(rate_limit_per_min=100000, retries=retries),
                      transport=FakeTransport(handler))


def offline_client() -> HttpClient:
    """transport 永远连不上（没有 429）。"""
    def handler(method: str, url: str, data, index: int):
        raise ProviderNetworkError("timeout")

    return HttpClient(HttpConfig(rate_limit_per_min=100000),
                      transport=FakeTransport(handler))


def make_ctx(tmp_path: Path, provider: FakeProvider, client: HttpClient) -> AppContext:
    """最小上下文。"""
    return AppContext(settings=Settings(), config_dir=tmp_path,
                      console=Console(stream=io.StringIO(), color="never", width=100),
                      registry=ProviderRegistry(providers=[provider]), cache=None,
                      client=client, prompter=None, interactive=False)


def write_profile(tmp_path: Path, count: int) -> Path:
    """写一份清单。"""
    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)
    profile = new_profile("p")
    profile.mods = [ModEntry(key="m" + str(i), display_name="M" + str(i), mod_id="m" + str(i),
                             sources={"modrinth": "m" + str(i)}) for i in range(count)]
    path = profile_path(tmp_path / "profiles", "p")
    save_profile(profile, path)
    return path


def modrinth_ctx(tmp_path: Path, client: HttpClient) -> AppContext:
    """用真实 Modrinth Provider（这样 429 会真的经过 HTTP 层）。"""
    from modcheck.providers.modrinth import ModrinthProvider

    return AppContext(settings=Settings(), config_dir=tmp_path,
                      console=Console(stream=io.StringIO(), color="never", width=100),
                      registry=ProviderRegistry(providers=[ModrinthProvider(client)]),
                      cache=None, client=client, prompter=None, interactive=False)


def run_with(tmp_path: Path, ctx: AppContext, count: int = 3):
    """跑一次 check 并返回 (退出码, 输出)。"""
    path = write_profile(tmp_path, count)
    args = Namespace(profile=None, file=str(path), mods_dir=None, mc="26.3", loader="fabric",
                     json_out=None, md_out=None, csv_out=None, refresh=False, jobs=1,
                     yes=True, pre=False, quiet=True, window=25, debug=False, no_color=True,
                     resolve=False)
    code = run_check(args, ctx)
    return code, ctx.console.stream.getvalue()  # type: ignore[attr-defined]


def test_rate_limited_produces_warning_and_incomplete_note(tmp_path: Path) -> None:
    """有模组因限流未判定 -> 报告里必须有警告，且结论标注不完整。"""
    ctx = modrinth_ctx(tmp_path, rate_limited_client())
    _, out = run_with(tmp_path, ctx)
    assert "因被 Modrinth 限流而未能判定" in out
    assert "3 个模组" in out
    assert "本次结果不完整" in out


def test_no_warning_when_no_rate_limit(tmp_path: Path) -> None:
    """没有 429 时不得无事生非地警告。"""
    ctx = modrinth_ctx(tmp_path, offline_client())
    _, out = run_with(tmp_path, ctx)
    assert "限流" not in out
    assert "本次结果不完整" not in out


def test_first_window_is_not_a_burst() -> None:
    """首窗不得一次性放行 limit 个：第 2 个请求就要等一个匀速间隔。"""
    limit = 60
    clock = FakeClock()
    limiter = RateLimiter(limit, clock=clock.clock, sleep=clock.sleep)
    limiter.acquire()
    assert clock.sleeps == []          # 第 1 个立即放行
    limiter.acquire()
    assert clock.sleeps, "第 2 个就该等一个 window/limit 的间隔"
    expected = 60.0 / limit
    assert abs(clock.sleeps[0] - expected) < 0.01
