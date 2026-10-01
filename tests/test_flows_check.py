"""flows/check_flow 单测：Report、进度回调、中途取消、数据源可用性（全程离线）。

流程层不许打印任何东西，也不许写盘；这里断言"返回了什么"与"回调被怎么调用"。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fakes import FakeProvider, FakeTransport, json_response
from modcheck.core.models import Loader, ModEntry, ProjectHit, SourceKind, Status, VersionInfo
from modcheck.core.report import Report
from modcheck.errors import ConfigError, ProviderNetworkError, ProviderRateLimited
from modcheck.flows.check_flow import (CheckStats, load_profile_entries, run_check_flow,
                                       source_unavailable)
from modcheck.providers.http import HttpConfig, HttpClient
from modcheck.providers.modrinth import ModrinthProvider
from modcheck.storage.profiles import new_profile, profile_path, save_profile


def V(pid: str, number: str, mc: tuple[str, ...], *, vtype: str = "release") -> VersionInfo:
    """构造版本对象。"""
    return VersionInfo.from_api({"id": pid + number, "project_id": pid, "version_number": number,
                                 "name": number, "date_published": "2026-09-18T00:00:00Z",
                                 "version_type": vtype, "game_versions": list(mc),
                                 "loaders": ["fabric"], "files": []})


def entry(key: str, **kw: object) -> ModEntry:
    """构造清单条目。"""
    return ModEntry(key=key, display_name=str(kw.pop("display", key)), mod_id=key,
                    sources={"modrinth": key}, source_kind=SourceKind.HASH, **kw)  # type: ignore[arg-type]


def write_profile(tmp_path: Path, entries: list[ModEntry], name: str = "demo") -> Path:
    """写一份测试清单。"""
    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)
    profile = new_profile(name)
    profile.mods = entries
    path = profile_path(tmp_path / "profiles", name)
    save_profile(profile, path)
    return path


class FakeCounters:
    """假的 HTTP 计数器（只暴露 flows 用到的三个只读属性）。"""

    def __init__(self, requests: int = 0, cache_hits: int = 0, successes: int = 0,
                 rate_limited: int = 0) -> None:
        self.requests = requests
        self._cache_hits = cache_hits
        self._successes = successes
        self._rate_limited = rate_limited

    @property
    def stats(self) -> tuple[int, int]:
        """(请求数, 缓存命中数)。"""
        return (self.requests, self._cache_hits)

    @property
    def successes(self) -> int:
        """成功次数。"""
        return self._successes

    @property
    def rate_limited(self) -> int:
        """429 次数。"""
        return self._rate_limited

    def bump_rate_limited(self) -> None:
        """模拟收到一次 429。"""
        self._rate_limited += 1


# ---------------------------------------------------------------- 返回 Report
def test_run_check_flow_returns_report(tmp_path: Path) -> None:
    """流程返回 Report（GUI 直接消费它，不需要任何终端）。"""
    provider = FakeProvider(releases={"ok": [V("ok", "26.3", ("26.3",))], "bad": []},
                            any_loader={"bad": []})
    entries = [entry("ok", display="Ok"), entry("bad", display="Bad")]
    report = run_check_flow(entries, provider=provider, loader=Loader.FABRIC, mc_version="26.3",
                            profile_name="demo")

    assert isinstance(report, Report)
    assert report.completed == 2 and report.total == 2
    assert report.interrupted is False
    assert report.summary["ready"] == 1 and report.summary["blocked"] == 1
    assert report.verdict().value == "blocked"
    assert report.profile_name == "demo"
    assert report.source_stats[SourceKind.HASH] == 2
    assert report.verify_identities()


def test_run_check_flow_uses_given_source_status(tmp_path: Path) -> None:
    """报告头的数据源文案由调用方注入（CLI 传 registry.status_line()）。"""
    provider = FakeProvider(releases={"ok": [V("ok", "26.3", ("26.3",))]})
    report = run_check_flow([entry("ok")], provider=provider, loader=Loader.FABRIC,
                            mc_version="26.3", source_status=("A", "B"))
    assert report.source_status == ("A", "B")


# ---------------------------------------------------------------- 进度回调
def test_progress_callbacks_are_ordered() -> None:
    """on_progress / on_item 每个模组各一次，done 从 1 递增到 N。"""
    provider = FakeProvider(releases={("m%d" % i): [V("m%d" % i, "26.3", ("26.3",))]
                                      for i in range(4)})
    entries = [entry("m%d" % i, display="Mod %d" % i) for i in range(4)]
    progress: list[tuple[int, int, str]] = []
    items: list[tuple[int, int, str]] = []

    report = run_check_flow(entries, provider=provider, loader=Loader.FABRIC, mc_version="26.3",
                            jobs=1,
                            on_progress=lambda d, t, n: progress.append((d, t, n)),
                            on_item=lambda d, t, e, i: items.append((d, t, e.key)))

    assert [done for done, _t, _n in progress] == [1, 2, 3, 4]
    assert {total for _d, total, _n in progress} == {4}
    assert [name for _d, _t, name in progress] == ["Mod 0", "Mod 1", "Mod 2", "Mod 3"]
    assert [done for done, _t, _k in items] == [1, 2, 3, 4]
    assert [key for _d, _t, key in items] == ["m0", "m1", "m2", "m3"]
    assert report.completed == 4


def test_progress_callbacks_are_optional() -> None:
    """不传回调也能跑完（GUI 一期之外的最小用法）。"""
    provider = FakeProvider(releases={"ok": [V("ok", "26.3", ("26.3",))]})
    report = run_check_flow([entry("ok")], provider=provider, loader=Loader.FABRIC,
                            mc_version="26.3")
    assert report.completed == 1


# ---------------------------------------------------------------- 中途取消
def test_should_stop_cancels_midway_without_residue(tmp_path: Path) -> None:
    """取消后返回 interrupted 报告：已完成的判定保留，且流程层什么都没写盘。"""
    provider = FakeProvider(releases={("m%d" % i): [V("m%d" % i, "26.3", ("26.3",))]
                                      for i in range(5)})
    entries = [entry("m%d" % i, display="Mod %d" % i) for i in range(5)]
    path = write_profile(tmp_path, entries)
    before = {p for p in tmp_path.rglob("*")}
    done: list[int] = []

    report = run_check_flow(entries, provider=provider, loader=Loader.FABRIC, mc_version="26.3",
                            jobs=1, profile_name="demo", profile_saved=True,
                            on_progress=lambda d, t, n: done.append(d),
                            should_stop=lambda: len(done) >= 2)

    assert report.interrupted is True
    assert report.completed == 2 and report.total == 5
    assert report.verdict().value == "interrupted"
    assert {p for p in tmp_path.rglob("*")} == before          # 不留半份落盘结果
    assert path.exists()                                        # （原有清单也没被动过）


def test_should_stop_false_is_not_interrupted() -> None:
    """探针恒为假 -> 正常跑完，不能误标成 interrupted（否则退出码会变成 130）。"""
    provider = FakeProvider(releases={("m%d" % i): [V("m%d" % i, "26.3", ("26.3",))]
                                      for i in range(3)})
    entries = [entry("m%d" % i) for i in range(3)]
    report = run_check_flow(entries, provider=provider, loader=Loader.FABRIC, mc_version="26.3",
                            jobs=1, should_stop=lambda: False)
    assert report.interrupted is False
    assert report.completed == 3


def test_keyboard_interrupt_returns_interrupted_report() -> None:
    """Ctrl+C（KeyboardInterrupt）不许冒泡：返回"查了多少算多少"的报告。"""
    provider = FakeProvider(raise_on={"releases_for_loader": KeyboardInterrupt()})
    report = run_check_flow([entry("m%d" % i) for i in range(3)], provider=provider,
                            loader=Loader.FABRIC, mc_version="26.3", jobs=1,
                            profile_name="demo")
    assert report.interrupted is True
    assert report.completed == 0
    assert report.total == 3
    assert report.summary["unknown"] == 0        # 中断路径不填统计（与 CLI 既有行为一致）


# ---------------------------------------------------------------- 数据源可用性
def test_source_unavailable_when_all_requests_failed() -> None:
    """真实 HttpClient + 永远连不上的 transport：所有请求失败 -> 数据源整体不可用。"""
    def handler(method: str, url: str, data, index: int):
        raise ProviderNetworkError("connection refused")

    client = HttpClient(HttpConfig(rate_limit_per_min=100000, retries=0),
                        transport=FakeTransport(handler))
    stats = CheckStats(client)
    report = run_check_flow([entry("carpet")], provider=ModrinthProvider(client),
                            loader=Loader.FABRIC, mc_version="26.3", jobs=1, stats=stats,
                            profile_name="demo")

    assert report.completed == 1
    assert report.summary["unknown"] == 1
    assert stats.requests_delta > 0 and stats.successes_delta == 0
    assert stats.requests_made == stats.requests_after
    assert source_unavailable(report, stats) is True


def test_source_available_when_some_request_succeeded() -> None:
    """有成功请求 -> 绝不能判成"数据源不可用"（那是误报，会让用户白折腾代理）。"""
    def handler(method: str, url: str, data, index: int):
        if "version_manifest" in url:
            raise ProviderNetworkError("offline")
        return json_response([{"id": "V1", "project_id": "carpet", "version_number": "26.3",
                               "name": "26.3", "date_published": "2026-09-18T00:00:00Z",
                               "version_type": "release", "game_versions": ["26.3"],
                               "loaders": ["fabric"], "files": []}])

    client = HttpClient(HttpConfig(rate_limit_per_min=100000, retries=0),
                        transport=FakeTransport(handler))
    stats = CheckStats(client)
    report = run_check_flow([entry("carpet")], provider=ModrinthProvider(client),
                            loader=Loader.FABRIC, mc_version="26.3", jobs=1, stats=stats)
    assert report.summary["ready"] == 1
    assert stats.successes_delta > 0
    assert source_unavailable(report, stats) is False


def test_zero_requests_during_check_is_not_source_unavailable() -> None:
    """检查前拉 Mojang 失败的请求**不算数**：检查区间 0 请求就不是"数据源不可用"。

    这是实测过的误报：Mojang 探测失败 + 清单里全是没匹配上的条目时，
    旧的"看总量"写法会把正常情况报成退出码 4。
    """
    counters = FakeCounters(requests=1, successes=0)     # 已经探测过一次 Mojang 且失败
    stats = CheckStats(counters)
    report = run_check_flow([ModEntry(key="mystery", display_name="Mystery")],
                            provider=FakeProvider(), loader=Loader.FABRIC, mc_version="26.3",
                            jobs=1, stats=stats)
    assert report.summary["unknown"] == 1
    assert stats.requests_delta == 0
    assert source_unavailable(report, stats) is False


def test_source_unavailable_false_without_stats() -> None:
    """不传 stats 就没有判据（GUI 不关心退出码的时候不该瞎报）。"""
    provider = FakeProvider(raise_on={"*": ProviderNetworkError("boom")})
    report = run_check_flow([entry("x")], provider=provider, loader=Loader.FABRIC,
                            mc_version="26.3", jobs=1)
    assert report.summary["unknown"] == 1
    assert source_unavailable(report, None) is False


def test_rate_limited_warning_is_added_by_flow() -> None:
    """被限流且有未判定项时，流程层负责把提示放进 report.warnings（CLI 只渲染）。"""
    counters = FakeCounters()

    class RateLimited(FakeProvider):
        """每次查询都报 429。"""

        def releases_for_loader(self, project_id, loader, *, window=25, prerelease=False):
            counters.bump_rate_limited()
            raise ProviderRateLimited("429", status=429, url="https://api.modrinth.com/x")

    stats = CheckStats(counters)
    report = run_check_flow([entry("x")], provider=RateLimited(), loader=Loader.FABRIC,
                            mc_version="26.3", jobs=1, stats=stats)
    assert report.summary["unknown"] == 1
    assert len(report.warnings) == 1
    assert "限流" in report.warnings[0]
    assert report.completed == 1


# ---------------------------------------------------------------- 清单来源
def test_load_profile_entries_from_file(tmp_path: Path) -> None:
    """--file：直接读那份清单，saved=True。"""
    path = write_profile(tmp_path, [entry("a"), entry("b")])
    source = load_profile_entries(profiles_dir=tmp_path / "profiles", file=str(path))
    assert [e.key for e in source.entries] == ["a", "b"]
    assert source.name == "demo"
    assert source.saved is True
    assert source.path == path


def test_load_profile_entries_from_profile_name(tmp_path: Path) -> None:
    """--profile：按名字在清单目录里找。"""
    write_profile(tmp_path, [entry("a")])
    source = load_profile_entries(profiles_dir=tmp_path / "profiles", profile="demo")
    assert [e.key for e in source.entries] == ["a"]
    assert source.saved is True


def test_load_profile_entries_from_mods_dir(tmp_path: Path) -> None:
    """--mods-dir：现场扫一遍文件夹，临时清单（saved=False，不写盘）。"""
    import make_fixtures

    mods = make_fixtures.make_mods_dir(tmp_path / "mods")
    seen: list[int] = []
    source = load_profile_entries(profiles_dir=tmp_path / "profiles", mods_dir=str(mods),
                                  provider=None,
                                  on_progress=lambda d, t, n: seen.append(d))
    assert source.saved is False
    assert source.path is None
    assert source.name == "mods"
    assert {e.mod_id for e in source.entries} >= {"carpet", "lithium", "fabric-api"}
    assert seen == list(range(1, len(seen) + 1))
    assert not (tmp_path / "profiles").exists()


def test_load_profile_entries_rejects_mutex(tmp_path: Path) -> None:
    """--profile 与 --mods-dir 互斥 -> ConfigError（退出码 3）。"""
    with pytest.raises(ConfigError):
        load_profile_entries(profiles_dir=tmp_path, profile="demo", mods_dir=str(tmp_path))


def test_load_profile_entries_missing_dir(tmp_path: Path) -> None:
    """--mods-dir 指向不存在的目录 -> ConfigError。"""
    with pytest.raises(ConfigError):
        load_profile_entries(profiles_dir=tmp_path, mods_dir=str(tmp_path / "nope"))


def test_load_profile_entries_missing_profile(tmp_path: Path) -> None:
    """清单不存在 -> ConfigError（并把可用清单列出来）。"""
    write_profile(tmp_path, [entry("a")], name="other")
    with pytest.raises(ConfigError) as exc:
        load_profile_entries(profiles_dir=tmp_path / "profiles", profile="demo")
    assert "other" in exc.value.message


def test_load_profile_entries_without_selection(tmp_path: Path) -> None:
    """既没给 --profile 也没给 --file/--mods-dir -> ConfigError。"""
    with pytest.raises(ConfigError):
        load_profile_entries(profiles_dir=tmp_path)


def test_load_profile_entries_is_cancellable_via_mods_dir(tmp_path: Path) -> None:
    """--mods-dir 那条扫描路径也要能把取消探针透传下去。"""
    import make_fixtures

    mods = make_fixtures.make_mods_dir(tmp_path / "mods")
    progress: list[int] = []

    source = load_profile_entries(profiles_dir=tmp_path / "profiles", mods_dir=str(mods),
                                  provider=FakeProvider(),
                                  on_progress=lambda d, t, n: progress.append(d),
                                  should_stop=lambda: len(progress) >= 1)
    assert progress == [1]
    assert source.entries == []          # 半份扫描结果不会被交给检查流程


# ---------------------------------------------------------------- 交互匹配回调
def test_interactive_match_is_forwarded() -> None:
    """交互匹配回调由 CLI 构造、流程转发给 core（非交互模式下不传，绝不提问）。"""
    provider = FakeProvider(hits=[ProjectHit("P9", "mystery", "Mystery", 1, "d", "fake")],
                            releases={"mystery": [V("mystery", "26.3", ("26.3",))]})
    calls: list[str] = []

    def matcher(picked: ModEntry, hits):
        calls.append(picked.key)
        picked.sources["modrinth"] = "mystery"
        return "mystery"

    entry_obj = ModEntry(key="mystery", display_name="Mystery", mod_id="mystery")
    report = run_check_flow([entry_obj], provider=provider, loader=Loader.FABRIC,
                            mc_version="26.3", jobs=1, interactive_match=matcher)
    assert calls == ["mystery"]
    assert report.summary["ready"] == 1
    assert report.groups[Status.READY][0].mod.sources["modrinth"] == "mystery"
