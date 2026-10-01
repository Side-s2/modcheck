"""R3-B02：core/downloader.py 的选品与文件名（离线，不联网）。"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from modcheck.core.downloader import (DOWNLOADABLE, MAX_FILENAME, DownloadItem, DownloadPlan,
                                      conflicts, download_all, extra_files_count,
                                      fallback_filename, overwrite_key, part_path, pick_file,
                                      pick_version, plan_for, safe_filename)
from modcheck.core.models import FileInfo, Loader, ModEntry, ReasonCode, Status, VersionInfo
from modcheck.core.report import Report, ReportItem
from modcheck.errors import ProviderRateLimited, ProviderVerifyError

OLD = "2000-01-01T00:00:00+08:00"


def file_info(name: str, *, primary: bool = False, size: int = 100) -> FileInfo:
    """造一个文件条目。"""
    return FileInfo(filename=name, url="https://cdn.example/" + name, primary=primary,
                    size=size, hashes={"sha1": "0" * 40})


def version(number: str = "1.0", *, files: tuple[FileInfo, ...] = (),
            channel: str = "release") -> VersionInfo:
    """造一个版本条目。"""
    return VersionInfo(version_id="V-" + number, version_number=number, name=number,
                       project_id="proj", date_published="2026-09-18T00:00:00Z",
                       version_type=channel, game_versions=("26.3",), loaders=("fabric",),
                       files=files)


def entry(key: str = "carpet", *, name: str = "", slug: str | None = None) -> ModEntry:
    """造一条清单记录。"""
    item = ModEntry(key=key, display_name=name or key, mod_id=key, updated_at=OLD)
    if slug:
        item.sources = {"modrinth": slug}
    return item


def report_item(mod: ModEntry, status: Status, *, latest: VersionInfo | None = None,
                compat: VersionInfo | None = None) -> ReportItem:
    """造一条报告条目。"""
    return ReportItem(mod=mod, status=status, reason=ReasonCode.OK, reason_key="reason.ok",
                      hint_key="advice.ok", latest_for_loader=latest, latest_compat=compat)


def make_report(*items: ReportItem) -> Report:
    """造一份报告。"""
    report = Report(mc_version="26.3", loader=Loader.FABRIC, profile_name="demo",
                    generated_at="2026-10-01T00:00:00+08:00")
    for item in items:
        report.add(item)
    return report


def test_plan_only_takes_ready_and_degraded(tmp_path: Path) -> None:
    """六组各一条：只有 🟢/🟡 进计划，其余按组记跳过原因。"""
    ready = version("26.3", files=(file_info("carpet-26.3.jar", primary=True),))
    old = version("26.1", files=(file_info("carpet-26.1.jar", primary=True),))
    report = make_report(
        report_item(entry("carpet", slug="carpet"), Status.READY, latest=ready),
        report_item(entry("sodium", slug="sodium"), Status.DEGRADED, latest=ready, compat=old),
        report_item(entry("create"), Status.BLOCKED, latest=old),
        report_item(entry("beta"), Status.PRERELEASE, latest=old),
        report_item(entry("unknown"), Status.UNKNOWN),
        report_item(entry("old"), Status.IGNORED, latest=old),
    )
    plan = plan_for(report, tmp_path)
    # 计划沿用报告的组顺序（🟡 在 🟢 前面），所以 sodium 先于 carpet
    assert [item.entry.key for item in plan.items] == ["sodium", "carpet"]
    assert [reason for _, reason in plan.skipped] == [
        "download.skip.status.blocked", "download.skip.status.prerelease",
        "download.skip.status.unknown", "download.skip.status.ignored",
    ]
    assert DOWNLOADABLE == (Status.READY, Status.DEGRADED)


def test_ready_takes_latest_and_degraded_takes_compat(tmp_path: Path) -> None:
    """🟢 取 latest_for_loader，🟡 取 latest_compat（PRD §14.1）。"""
    latest = version("26.3", files=(file_info("new-26.3.jar", primary=True),))
    compat = version("26.1", files=(file_info("old-26.1.jar", primary=True),))
    report = make_report(
        report_item(entry("a"), Status.READY, latest=latest, compat=compat),
        report_item(entry("b"), Status.DEGRADED, latest=latest, compat=compat),
    )
    plan = plan_for(report, tmp_path)
    by_key = {item.entry.key: item for item in plan.items}
    assert by_key["a"].version is latest and by_key["a"].target.name == "new-26.3.jar"
    assert by_key["b"].version is compat and by_key["b"].target.name == "old-26.1.jar"


def test_degraded_without_compat_is_skipped(tmp_path: Path) -> None:
    """🟡 但「可用」版本缺失 -> 跳过（PRD §14.5 第 17 条）。"""
    report = make_report(report_item(entry("a"), Status.DEGRADED, latest=version("26.3")))
    plan = plan_for(report, tmp_path)
    assert plan.items == ()
    assert plan.skipped[0][1] == "download.skip.no_version"


def test_pick_file_prefers_primary_jar() -> None:
    """只下 primary 的 .jar；附加文件（sources）不算（D49）。"""
    version_with = version("1.0", files=(
        file_info("mod-1.0-sources.jar"),
        file_info("mod-1.0.jar", primary=True),
    ))
    assert pick_file(version_with).filename == "mod-1.0.jar"


def test_pick_file_falls_back_to_first_jar() -> None:
    """没有 primary 标记时取第一个 .jar（跳过非 jar 的附件）。"""
    version_with = version("1.0", files=(
        file_info("mod-1.0.zip"),
        file_info("mod-1.0.jar"),
        file_info("mod-1.0-dev.jar"),
    ))
    assert pick_file(version_with).filename == "mod-1.0.jar"


def test_pick_file_without_jar(tmp_path: Path) -> None:
    """一个 .jar 都没有 -> 跳过并记原因（PRD §14.5 第 2 条）。"""
    empty = version("1.0", files=(file_info("mod-1.0.zip"),))
    assert pick_file(empty) is None
    report = make_report(report_item(entry("a"), Status.READY, latest=empty))
    plan = plan_for(report, tmp_path)
    assert plan.items == () and plan.skipped[0][1] == "download.skip.no_jar"


def test_pick_version_other_statuses() -> None:
    """非 🟢/🟡 的组没有可下载版本。"""
    item = report_item(entry("a"), Status.PRERELEASE, latest=version("1.0"))
    assert pick_version(item) is None


def test_filename_fallback_uses_slug_and_version() -> None:
    """文件名为空 -> {slug}-{version_number}.jar（PRD §14.5 第 3 条）。"""
    version_info = version("26.3")
    assert fallback_filename(entry("carpet", slug="Carpet-Project"), version_info) == (
        "Carpet-Project-26.3.jar")
    assert fallback_filename(entry("carpet"), version_info) == "carpet-26.3.jar"
    assert fallback_filename(entry(""), version_info) == "mod-26.3.jar"


def test_filename_fallback_when_version_number_empty() -> None:
    """版本号也拿不到时用 unknown 占位，绝不产生空文件名。"""
    blank = VersionInfo(version_id="", version_number="", name="", project_id="p",
                        date_published="", version_type="release", game_versions=(),
                        loaders=(), files=())
    assert fallback_filename(entry("carpet"), blank) == "carpet-unknown.jar"


def test_plan_uses_fallback_when_file_name_empty(tmp_path: Path) -> None:
    """filename 为空时计划里用兜底名。"""
    item_version = version("26.3", files=(file_info("", primary=True),))
    report = make_report(report_item(entry("carpet", slug="carpet"), Status.READY,
                                     latest=item_version))
    plan = plan_for(report, tmp_path)
    assert plan.items[0].target.name == "carpet-26.3.jar"


def test_plan_joins_target_dir(tmp_path: Path) -> None:
    """target 是 目标目录 / 文件名，且 plan_for 不创建目录。"""
    sub = tmp_path / "downloads"
    report = make_report(report_item(
        entry("a"), Status.READY, latest=version("1.0", files=(file_info("a-1.0.jar"),))))
    plan = plan_for(report, sub)
    assert plan.items[0].target == sub / "a-1.0.jar"
    assert not sub.exists()


def test_safe_filename_basics() -> None:
    """空名兜底、非法字符替换、控制字符替换、首尾处理。"""
    assert safe_filename("", fallback="x-1.0.jar") == "x-1.0.jar"
    assert safe_filename("   ", fallback="x-1.0.jar") == "x-1.0.jar"
    assert safe_filename("  a-1.0.jar  ", fallback="x.jar") == "a-1.0.jar"
    assert safe_filename('a:b*c?d"e<f>g|h.jar', fallback="x.jar") == "a_b_c_d_e_f_g_h.jar"
    assert safe_filename("a" + chr(92) + "b/c.jar", fallback="x.jar") == "a_b_c.jar"
    assert safe_filename("tab" + chr(9) + "name.jar", fallback="x.jar") == "tab_name.jar"
    assert safe_filename("trailing...", fallback="x.jar") == "trailing"


def test_safe_filename_truncates_keeping_jar() -> None:
    """超长名截断到 200 字符且保留 .jar 后缀。"""
    long_name = "m" * 300 + ".jar"
    result = safe_filename(long_name, fallback="x.jar")
    assert len(result) == MAX_FILENAME and result.endswith(".jar")
    no_suffix = safe_filename("n" * 300, fallback="x.jar")
    assert len(no_suffix) == MAX_FILENAME and not no_suffix.endswith(".jar")


def test_safe_filename_never_empty() -> None:
    """全是非法字符时得到替换后的非空名（不产生空文件名）。"""
    result = safe_filename("???", fallback="")
    assert result == "___"
    assert safe_filename("...", fallback="") != ""


def test_conflicts_detects_existing_files(tmp_path: Path) -> None:
    """目标目录里已有同名文件 -> 出现在 conflicts 里。"""
    (tmp_path / "a-1.0.jar").write_bytes(b"x")
    report = make_report(
        report_item(entry("a"), Status.READY, latest=version("1.0", files=(file_info("a-1.0.jar"),))),
        report_item(entry("b"), Status.READY, latest=version("1.0", files=(file_info("b-1.0.jar"),))),
    )
    plan = plan_for(report, tmp_path)
    found = conflicts(plan)
    assert [item.target.name for item in found] == ["a-1.0.jar"]
    assert overwrite_key(found[0]) == "a-1.0.jar"


def test_extra_files_count(tmp_path: Path) -> None:
    """附加文件计数（汇总里的 ℹ 行）。"""
    multi = version("1.0", files=(file_info("a.jar", primary=True), file_info("a-sources.jar")))
    single = version("1.0", files=(file_info("b.jar", primary=True),))
    report = make_report(
        report_item(entry("a"), Status.READY, latest=multi),
        report_item(entry("b"), Status.READY, latest=single),
    )
    assert extra_files_count(plan_for(report, tmp_path)) == 1


def test_part_path_and_empty_plan(tmp_path: Path) -> None:
    """.part 路径与空计划。"""
    assert part_path(tmp_path / "a.jar").name == "a.jar.part"
    plan = DownloadPlan(items=(), skipped=())
    assert conflicts(plan) == () and extra_files_count(plan) == 0


# ---------------------------------------------------------------- R3-B03：download_all
class FakeFetcher:
    """假 fetcher：本地写文件，可注入延迟 / 失败 / 限流 / 校验失败。"""

    def __init__(self, *, payload: bytes = b"0123456789", delay: float = 0.0,
                 fail_times: int = 0, verify_fail_times: int = 0, rate_limit_times: int = 0,
                 always_fail: Exception | None = None, write_part: bool = True,
                 on_call: object = None) -> None:
        self.payload = payload
        self.delay = delay
        self.fail_times = fail_times
        self.verify_fail_times = verify_fail_times
        self.rate_limit_times = rate_limit_times
        self.always_fail = always_fail
        self.write_part = write_part
        self.on_call = on_call
        self.calls: list[str] = []
        self.live = 0
        self.max_live = 0
        self.lock = threading.Lock()

    def download(self, url: str, dest: Path, *, sha1: str | None = None,
                 on_chunk=None, timeout: float | None = None) -> int:
        """模拟 HttpClient.download 的对外行为（含 .part 与原子替换）。"""
        with self.lock:
            self.calls.append(dest.name)
            self.live += 1
            self.max_live = max(self.max_live, self.live)
            if callable(self.on_call):
                self.on_call(len(self.calls))
        try:
            if self.rate_limit_times > 0:
                with self.lock:
                    self.rate_limit_times -= 1
                raise ProviderRateLimited("429", status=429, url=url)
            if self.always_fail is not None:
                raise self.always_fail
            if self.verify_fail_times > 0:
                with self.lock:
                    self.verify_fail_times -= 1
                raise ProviderVerifyError("bad sha1")
            if self.fail_times > 0:
                with self.lock:
                    self.fail_times -= 1
                raise OSError("disk full")
            if self.delay:
                time.sleep(self.delay)
            dest.parent.mkdir(parents=True, exist_ok=True)
            part = dest.with_name(dest.name + ".part") if self.write_part else dest
            with part.open("wb") as handle:
                handle.write(self.payload)
            if on_chunk is not None:
                on_chunk(len(self.payload))
            if part != dest:
                os.replace(part, dest)
            return len(self.payload)
        finally:
            with self.lock:
                self.live -= 1


def make_plan(tmp_path: Path, count: int = 3, *, size: int = 10) -> DownloadPlan:
    """造一个有 count 个文件的下载计划。"""
    items = []
    for index in range(count):
        name = "mod" + str(index) + "-1.0.jar"
        items.append(DownloadItem(
            entry=entry("mod" + str(index)),
            version=version("1.0", files=(file_info(name, primary=True, size=size),)),
            file=file_info(name, primary=True, size=size),
            target=tmp_path / name))
    return DownloadPlan(items=tuple(items), skipped=())


def test_download_all_ok(tmp_path: Path) -> None:
    """正常下载：全部 ok、字节数正确、文件真的落盘、报文里没有 .part。"""
    plan = make_plan(tmp_path, 3)
    fetcher = FakeFetcher()
    report = download_all(plan, fetcher, sleep=lambda _s: None)
    assert (report.ok, report.skipped, report.failed, report.cancelled) == (3, 0, 0, False)
    assert report.bytes_total == 30
    assert report.elapsed >= 0.0
    assert (tmp_path / "mod0-1.0.jar").read_bytes() == fetcher.payload
    assert not list(tmp_path.glob("*.part"))
    assert [item.status for item in report.items] == ["ok", "ok", "ok"]


def test_download_all_empty_plan(tmp_path: Path) -> None:
    """空计划：全 0，不报错。"""
    report = download_all(DownloadPlan(items=(), skipped=()), FakeFetcher())
    assert (report.ok, report.skipped, report.failed, report.bytes_total) == (0, 0, 0, 0)


def test_download_all_overwrite_false_skips(tmp_path: Path) -> None:
    """overwrite=False 的条目直接跳过，不发请求、不写盘。"""
    plan = make_plan(tmp_path, 2)
    fetcher = FakeFetcher()
    report = download_all(plan, fetcher, overwrite={"mod0-1.0.jar": False},
                          sleep=lambda _s: None)
    assert (report.ok, report.skipped, report.failed) == (1, 1, 0)
    assert fetcher.calls == ["mod1-1.0.jar"]
    assert not (tmp_path / "mod0-1.0.jar").exists()
    assert report.items[0].status == "skipped"
    assert report.items[0].message_key == "download.skip.user"


def test_download_all_retries_then_succeeds(tmp_path: Path) -> None:
    """前两次失败、第三次成功：重试 2 次，退避 1s / 2s。"""
    plan = make_plan(tmp_path, 1)
    fetcher = FakeFetcher(fail_times=2)
    sleeps: list[float] = []
    report = download_all(plan, fetcher, sleep=sleeps.append)
    assert report.ok == 1 and report.failed == 0
    assert len(fetcher.calls) == 3
    assert sleeps == [1.0, 2.0]


def test_download_all_gives_up_after_retries(tmp_path: Path) -> None:
    """一直失败：重试 2 次后记 failed，且不影响其它文件。"""
    plan = make_plan(tmp_path, 2)
    fetcher = FakeFetcher(fail_times=99)
    sleeps: list[float] = []
    report = download_all(plan, fetcher, sleep=sleeps.append)
    assert (report.ok, report.failed) == (0, 2)
    assert all(item.status == "failed" for item in report.items)
    assert report.items[0].message_key == "download.error.write"
    assert sleeps == [1.0, 2.0, 1.0, 2.0]
    assert not list(tmp_path.glob("*.part"))


class SelectiveFetcher(FakeFetcher):
    """只让某一个文件失败，其余正常（验证失败隔离）。"""

    def __init__(self, bad_name: str, **kw) -> None:
        super().__init__(**kw)
        self.bad_name = bad_name

    def download(self, url: str, dest: Path, *, sha1: str | None = None,
                 on_chunk=None, timeout: float | None = None) -> int:
        if dest.name == self.bad_name:
            with self.lock:
                self.calls.append(dest.name)
            raise OSError("disk full")
        return super().download(url, dest, sha1=sha1, on_chunk=on_chunk, timeout=timeout)


def test_download_all_partial_failure(tmp_path: Path) -> None:
    """一个文件失败不影响其它文件（PRD §14.5 第 6 条）。"""
    plan = make_plan(tmp_path, 3)
    fetcher = SelectiveFetcher("mod0-1.0.jar")
    report = download_all(plan, fetcher, jobs=1, retries=0, sleep=lambda _s: None)
    assert (report.ok, report.failed) == (2, 1)
    assert report.items[0].status == "failed"
    assert (tmp_path / "mod1-1.0.jar").exists() and (tmp_path / "mod2-1.0.jar").exists()
    assert not (tmp_path / "mod0-1.0.jar").exists()


def test_download_all_verify_failure(tmp_path: Path) -> None:
    """sha1 校验失败：记 verify_failed，重试 2 次后仍失败 -> failed 计数。"""
    plan = make_plan(tmp_path, 1)
    fetcher = FakeFetcher(verify_fail_times=99)
    report = download_all(plan, fetcher, sleep=lambda _s: None)
    assert report.failed == 1
    assert report.items[0].status == "verify_failed"
    assert report.items[0].message_key == "download.error.verify"
    assert len(fetcher.calls) == 3


def test_download_all_rate_limit_not_counted(tmp_path: Path) -> None:
    """429 不计入重试次数：retries=0 也能靠放行成功。"""
    plan = make_plan(tmp_path, 1)
    fetcher = FakeFetcher(rate_limit_times=2)
    sleeps: list[float] = []
    report = download_all(plan, fetcher, retries=0, sleep=sleeps.append)
    assert report.ok == 1 and len(fetcher.calls) == 3 and sleeps == []


def test_download_all_rate_limit_gives_up(tmp_path: Path) -> None:
    """一直 429 时不会死循环（有硬上限）。"""
    plan = make_plan(tmp_path, 1)
    fetcher = FakeFetcher(rate_limit_times=99)
    report = download_all(plan, fetcher, retries=0, sleep=lambda _s: None)
    assert report.failed == 1 and len(fetcher.calls) == 6


def test_download_all_jobs_are_parallel(tmp_path: Path) -> None:
    """jobs=3 时三个文件并行下载（用最慢时刻的并发数断言）。"""
    plan = make_plan(tmp_path, 3)
    fetcher = FakeFetcher(delay=0.05)
    report = download_all(plan, fetcher, jobs=3, sleep=lambda _s: None)
    assert report.ok == 3
    assert fetcher.max_live == 3
    assert report.elapsed < 0.15


def test_download_all_jobs_one_is_serial(tmp_path: Path) -> None:
    """jobs=1 时严格串行（并发数恒为 1）。"""
    plan = make_plan(tmp_path, 3)
    fetcher = FakeFetcher(delay=0.02)
    download_all(plan, fetcher, jobs=1, sleep=lambda _s: None)
    assert fetcher.max_live == 1


def test_download_all_progress_callback(tmp_path: Path) -> None:
    """on_progress 收到 (item, 已下载, 总大小)。"""
    plan = make_plan(tmp_path, 1, size=10)
    seen: list[tuple[str, int, int]] = []
    download_all(plan, FakeFetcher(payload=b"x" * 10), sleep=lambda _s: None,
                 on_progress=lambda item, done, total: seen.append((item.target.name, done, total)))
    assert seen == [("mod0-1.0.jar", 10, 10)]


def test_download_all_cancelled_before_start(tmp_path: Path) -> None:
    """开始前就取消：一个请求都不发，全部记 cancelled。"""
    plan = make_plan(tmp_path, 2)
    fetcher = FakeFetcher()
    event = threading.Event()
    event.set()
    report = download_all(plan, fetcher, cancel=event, sleep=lambda _s: None)
    assert report.cancelled is True and fetcher.calls == []
    assert [item.status for item in report.items] == ["cancelled", "cancelled"]


def test_download_all_cancel_midway_cleans_parts(tmp_path: Path) -> None:
    """下到一半取消：已完成文件保留、未开始的记 cancelled、残留 .part 被清理。"""
    plan = make_plan(tmp_path, 3)
    event = threading.Event()
    left_part = tmp_path / "mod2-1.0.jar.part"
    left_part.write_bytes(b"partial")
    fetcher = FakeFetcher(on_call=lambda index: event.set() if index >= 1 else None)
    report = download_all(plan, fetcher, cancel=event, jobs=1, sleep=lambda _s: None)
    assert report.cancelled is True
    assert fetcher.calls == ["mod0-1.0.jar"]
    assert (tmp_path / "mod0-1.0.jar").exists()
    assert not left_part.exists()
    assert report.items[0].status == "ok"
    assert [item.status for item in report.items[1:]] == ["cancelled", "cancelled"]


def test_download_all_closes_part_on_failure(tmp_path: Path) -> None:
    """fetcher 抛异常时留下的 .part 由 download_all 兜底清理（最终失败后）。"""
    plan = make_plan(tmp_path, 1)
    broken = tmp_path / "mod0-1.0.jar.part"
    broken.write_bytes(b"half")

    def download(url, dest, *, sha1=None, on_chunk=None, timeout=None):
        raise ProviderVerifyError("bad")

    report = download_all(plan, download, retries=1, sleep=lambda _s: None)
    assert report.failed == 1
    assert not part_path(plan.items[0].target).exists()

