"""flows/scan_flow 单测：结构化结果、进度回调、中途取消（全程离线，假 Provider）。

流程层不许打印任何东西，也不许写盘 —— 所以这里断言的是"返回了什么"与"回调被怎么调用"。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from fakes import FakeProvider
from modcheck.core.models import MatchStatus, ProjectHit, SourceKind
from modcheck.errors import ConfigError, ProviderUnavailable
from modcheck.flows.scan_flow import ScanReport, scan_dirs, scan_from_list

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_fixtures  # noqa: E402


def make_provider() -> FakeProvider:
    """能认出 carpet / fabric-api / lithium 的假数据源。"""
    hits = [ProjectHit("Pcarpet", "carpet", "Carpet", 1, "d", "fake"),
            ProjectHit("Papi", "fabric-api", "Fabric API", 1, "d", "fake"),
            ProjectHit("Pli", "lithium", "Lithium", 1, "d", "fake")]
    return FakeProvider(hits=hits)


def mods_dir(tmp_path: Path) -> Path:
    """现场生成 mods 文件夹（6 个文件 + 1 个子目录，见 make_fixtures）。"""
    return make_fixtures.make_mods_dir(tmp_path / "mods")


# ---------------------------------------------------------------- 结构化结果
def test_scan_returns_structured_report(tmp_path: Path) -> None:
    """流程返回的是纯数据结构：条目 / 跳过 / 子目录 / 统计，一个都不少。"""
    mods = mods_dir(tmp_path)
    report = scan_dirs([mods], provider=make_provider())

    assert isinstance(report, ScanReport)
    assert report.cancelled is False
    assert report.files_seen == 8                      # 8 个文件（子目录不算文件）
    assert report.by_meta >= 3                         # carpet / lithium / fabric-api 有元数据
    assert report.by_search >= 3                       # 三个都被同名搜索确认
    assert len(report.skipped) == 3                    # README / .disabled / broken
    assert report.subdirs == ["1.20.1-backup"]
    assert report.offline is False

    carpet = next(e for e in report.entries if e.mod_id == "carpet")
    assert carpet.key == "slug:modrinth:carpet"
    assert carpet.match_status is MatchStatus.EXACT
    assert carpet.source_kind is SourceKind.SEARCH
    # 每条 entry 都是构造完整的（cancelled 时也不会有"写了一半"的条目）
    assert all(entry.key and entry.file_name for entry in report.entries)


def test_scan_without_provider_degrades_but_still_returns_entries(tmp_path: Path) -> None:
    """没有数据源 = None：只用 jar 内信息，条目照样齐全，只多一条 offline 提示。"""
    mods = mods_dir(tmp_path)
    report = scan_dirs([mods], provider=None)
    assert report.offline is True
    assert report.warnings
    assert {e.mod_id for e in report.entries} >= {"carpet", "lithium", "fabric-api"}


# ---------------------------------------------------------------- 进度回调
def test_progress_callback_is_ordered(tmp_path: Path) -> None:
    """on_progress 按"读一个报一个"的顺序调用：(1..N, 总数一致, 与文件顺序相同)。"""
    mods = mods_dir(tmp_path)
    calls: list[tuple[int, int, str]] = []
    scan_dirs([mods], provider=make_provider(),
              on_progress=lambda done, total, name: calls.append((done, total, name)))

    assert len(calls) == 6                              # 5 个 jar + 1 个损坏 jar
    assert [done for done, _total, _name in calls] == list(range(1, len(calls) + 1))
    assert {total for _done, total, _name in calls} == {len(calls)}
    # 文件名按目录内排序给出（与扫描顺序一致）
    assert [name for _done, _total, name in calls] == sorted(name for _d, _t, name in calls)
    assert "broken.jar" in [name for _done, _total, name in calls]


def test_progress_callback_is_optional(tmp_path: Path) -> None:
    """不传回调也能跑（GUI/纯逻辑调用方不该被迫造一个）。"""
    report = scan_dirs([mods_dir(tmp_path)], provider=make_provider())
    assert report.entries


# ---------------------------------------------------------------- 中途取消
def test_should_stop_cancels_midway_without_residue(tmp_path: Path) -> None:
    """读 jar 阶段就能被叫停：不是"循环外判一次"，而且**不留下半份结果**。"""
    mods = mods_dir(tmp_path)
    progress: list[str] = []

    def on_progress(done: int, total: int, name: str) -> None:
        progress.append(name)

    report = scan_dirs([mods], provider=make_provider(), on_progress=on_progress,
                       should_stop=lambda: len(progress) >= 2)

    assert report.cancelled is True
    assert len(progress) == 2                  # 第 3 个文件之前就停了
    assert report.entries == []                # 半份条目绝不冒充完整结果
    assert report.skipped == []
    assert not list(tmp_path.rglob("*.json"))  # 流程层不落盘：没有任何残状态


def test_should_stop_before_first_jar(tmp_path: Path) -> None:
    """一开始就取消：立刻返回，一个文件都不读。"""
    mods = mods_dir(tmp_path)
    report = scan_dirs([mods], provider=make_provider(), should_stop=lambda: True)
    assert report.cancelled is True
    assert report.entries == [] and report.skipped == []
    assert report.files_seen == 0


def test_should_stop_false_never_cancels(tmp_path: Path) -> None:
    """探针恒为假 -> 正常跑完，cancelled 必须是假（调用方据此决定能不能落盘）。"""
    report = scan_dirs([mods_dir(tmp_path)], provider=make_provider(),
                       should_stop=lambda: False)
    assert report.cancelled is False
    assert report.entries


def test_cancel_during_name_search_phase(tmp_path: Path) -> None:
    """搜索阶段（逐个出网）也要能取消，而不是把整轮搜索跑完。"""
    class StoppingProvider(FakeProvider):
        """第一次搜索后就让 should_stop 变真。"""

        def __init__(self, **kw: object) -> None:
            super().__init__(**kw)  # type: ignore[arg-type]
            self.searched = False

        def search(self, query: str, limit: int = 10):
            self.searched = True
            return super().search(query, limit)

    provider = StoppingProvider(hits=[ProjectHit("Pcarpet", "carpet", "Carpet", 1, "d", "fake")])
    report = scan_dirs([mods_dir(tmp_path)], provider=provider,
                       should_stop=lambda: provider.searched)
    assert provider.searched is True
    assert report.cancelled is True


# ---------------------------------------------------------------- --from-list
def test_scan_from_list_reports_progress_and_cancels(tmp_path: Path) -> None:
    """文件名清单模式：逐行报进度；取消后只返回已经解析完的那几行。"""
    listing = tmp_path / "list.txt"
    listing.write_text("carpet-26.1.jar\nlithium-0.12.1.jar\njei-26.1.jar\ncreate-1.20.1.jar\n",
                       encoding="utf-8")
    calls: list[int] = []

    def on_progress(done: int, total: int, name: str) -> None:
        calls.append(done)

    report = scan_from_list(listing, provider=make_provider(), on_progress=on_progress,
                            should_stop=lambda: len(calls) >= 2)

    assert calls == [1, 2]
    assert report.cancelled is True
    assert len(report.entries) == 2
    assert report.files_seen == 4


def test_scan_from_list_without_provider_is_offline(tmp_path: Path) -> None:
    """没有数据源时不该崩，也不该丢条目（只是全部停在"未判定"）。"""
    listing = tmp_path / "list.txt"
    listing.write_text("carpet-26.1.jar\nlithium-0.12.1.jar\n", encoding="utf-8")
    report = scan_from_list(listing, provider=None)
    assert len(report.entries) == 2
    assert report.offline is True
    assert report.cancelled is False


def test_scan_from_list_requires_readable_file(tmp_path: Path) -> None:
    """读不到文件 -> ConfigError（流程层不打印、不 sys.exit）。"""
    with pytest.raises(ConfigError):
        scan_from_list(tmp_path / "nope.txt", provider=None)


def test_scan_dirs_requires_existing_directory(tmp_path: Path) -> None:
    """目录不存在 -> ConfigError（参数错误是调用方的事，流程层只抛领域异常）。"""
    with pytest.raises(ConfigError):
        scan_dirs([tmp_path / "nope"], provider=None)


def test_scan_offline_provider_error_is_not_fatal(tmp_path: Path) -> None:
    """数据源整体不可用（ProviderUnavailable）不中断扫描。"""
    provider = FakeProvider(raise_on={"*": ProviderUnavailable("offline")})
    report = scan_dirs([mods_dir(tmp_path)], provider=provider)
    assert report.offline is True
    assert {e.mod_id for e in report.entries} >= {"carpet", "lithium", "fabric-api"}
