"""R3-B04 ~ R3-B12：flows/download_flow 的编排单测（全程离线，假 fetcher）。

流程层不许打印、不许询问、不许决定屏幕长什么样 —— 所以这里断言的是
"返回了什么 / 回调被怎么调用 / 磁盘上剩了什么"。
覆盖父任务点名的场景：成功、sha1 不符、404、429、取消、磁盘写失败、重试耗尽。
"""
from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

import pytest

from modcheck.core.downloader import (SKIP_NO_JAR, SKIP_NO_VERSION, STATUS_CANCELLED,
                                      STATUS_FAILED, STATUS_OK, STATUS_SKIPPED,
                                      STATUS_VERIFY_FAILED)
from modcheck.core.models import FileInfo, Loader, ModEntry, ReasonCode, Status, VersionInfo
from modcheck.core.report import Report, ReportItem
from modcheck.errors import ProviderHTTPError, ProviderRateLimited, ProviderVerifyError
from modcheck.providers.http import HttpConfig, HttpClient
from modcheck.flows.download_flow import (TARGET_IS_FILE, TARGET_MISSING, TARGET_NOT_WRITABLE,
                                          UNKNOWN_FREE, check_target_dir, ensure_target_dir,
                                          looks_like_mods_dir, plan_skips, prepare_download,
                                          run_download_flow)


# ---------------------------------------------------------------- 造数据
def file_info(name: str, *, primary: bool = False, size: int = 100,
              sha1: str = "0" * 40) -> FileInfo:
    """造一个文件条目。"""
    return FileInfo(filename=name, url="https://cdn.example/" + name, primary=primary,
                    size=size, hashes={"sha1": sha1})


def version(number: str = "1.0", *, files: tuple[FileInfo, ...] = ()) -> VersionInfo:
    """造一个版本条目。"""
    return VersionInfo(version_id="V-" + number, version_number=number, name=number,
                       project_id="proj", date_published="2026-09-18T00:00:00Z",
                       version_type="release", game_versions=("26.3",), loaders=("fabric",),
                       files=files)


def entry(key: str, *, name: str = "") -> ModEntry:
    """造一条清单记录。"""
    return ModEntry(key=key, display_name=name or key, mod_id=key,
                    sources={"modrinth": key})


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


def sample_report(*, extra: bool = False) -> Report:
    """两条可下载（🟢 / 🟡）+ 一条阻塞 + 一条没 jar。"""
    ready = version("26.3", files=(file_info("carpet-26.3.jar", primary=True, size=100),))
    compat = version("26.1", files=(file_info("lithium-26.1.jar", primary=True, size=200),))
    addon = version("26.3", files=(file_info("jei-26.3-sources.jar", primary=True),))
    return make_report(
        report_item(entry("carpet"), Status.READY, latest=ready),
        report_item(entry("lithium"), Status.DEGRADED, latest=ready, compat=compat),
        report_item(entry("create"), Status.BLOCKED, latest=ready),
        report_item(entry("jei"), Status.READY, latest=addon),
    )


def one_ready_report(name: str = "carpet-26.3.jar") -> Report:
    """只有一个 🟢 可下载文件的报告（很多用例只需要一个文件）。"""
    return make_report(report_item(entry("carpet"), Status.READY,
                                   latest=version("26.3",
                                                  files=(file_info(name, primary=True),))))


class FakeFetcher:
    """假 fetcher：本地写文件，可注入延迟 / 失败 / 限流 / 校验失败。"""

    def __init__(self, *, payload: bytes = b"0123456789", delay: float = 0.0,
                 fail_times: int = 0, verify_times: int = 0, rate_limit_times: int = 0,
                 error: Exception | None = None, fail_names: tuple[str, ...] = (),
                 on_call=None) -> None:
        self.payload = payload
        self.delay = delay
        self.fail_times = fail_times
        self.verify_times = verify_times
        self.rate_limit_times = rate_limit_times
        self.error = error
        self.fail_names = fail_names
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
            if self.error is not None and dest.name in self.fail_names:
                raise self.error
            if self.verify_times > 0:
                with self.lock:
                    self.verify_times -= 1
                raise ProviderVerifyError("bad sha1", hint="再下一次")
            if self.fail_times > 0:
                with self.lock:
                    self.fail_times -= 1
                raise OSError("disk full")
            if self.delay:
                time.sleep(self.delay)
            dest.parent.mkdir(parents=True, exist_ok=True)
            part = dest.with_name(dest.name + ".part")
            with part.open("wb") as handle:
                handle.write(self.payload)
            if on_chunk is not None:
                on_chunk(len(self.payload))
            part.replace(dest)
            return len(self.payload)
        finally:
            with self.lock:
                self.live -= 1


def no_sleep(_seconds: float) -> None:
    """测试里不真的等待。"""


# ---------------------------------------------------------------- 选品（prepare_download）
def test_prepare_takes_only_downloadable_and_builds_targets(tmp_path: Path) -> None:
    """只有 🟢/🟡 进计划；🟡 取「可用」版本；target 拼在目标目录下。"""
    prep = prepare_download(sample_report(), tmp_path)
    # 计划沿用报告的组顺序（🔴 🟠 🟡 ⚪ 🟢），所以 🟡 的 lithium 排在 🟢 的 carpet 前面
    assert [item.entry.key for item in prep.items] == ["lithium", "carpet"]
    by_key = {item.entry.key: item for item in prep.items}
    assert by_key["carpet"].target.name == "carpet-26.3.jar"
    assert by_key["carpet"].version.version_number == "26.3"       # 🟢 取最新版
    assert by_key["lithium"].target.name == "lithium-26.1.jar"
    assert by_key["lithium"].version.version_number == "26.1"      # 🟡 取「可用」的旧稳定版
    assert prep.total == 2 and prep.has_work is True
    assert prep.extra_files == 0


def test_prepare_classifies_skips_by_reason(tmp_path: Path) -> None:
    """没有可下载 .jar 的（§14.5 第 2 条）与 🟡 缺「可用」版本的（第 17 条）分开给出。"""
    report = make_report(
        report_item(entry("jei"), Status.READY,
                    latest=version("26.3", files=(file_info("jei-26.3-sources.jar",
                                                            primary=True),))),
        report_item(entry("old"), Status.DEGRADED, latest=version("26.3")),
    )
    prep = prepare_download(report, tmp_path)
    assert prep.items == ()
    assert [item.key for item in prep.no_jar] == ["jei"]
    assert [item.key for item in prep.no_version] == ["old"]
    assert plan_skips(prep.plan, SKIP_NO_JAR) == prep.no_jar
    assert plan_skips(prep.plan, SKIP_NO_VERSION) == prep.no_version
    # 🟡（old）在报告里排在 🟢（jei）前面
    assert [key for _entry, key in prep.plan.skipped] == [SKIP_NO_VERSION, SKIP_NO_JAR]


def test_prepare_total_bytes_for_space_check(tmp_path: Path) -> None:
    """总字节数给空间预检查用（§14.5 第 16 条）。"""
    prep = prepare_download(sample_report(), tmp_path)
    assert prep.total_bytes == 300                     # 100 + 200


def test_prepare_counts_extra_files(tmp_path: Path) -> None:
    """有附加文件的模组要被数出来（汇总里的 ℹ 行）。"""
    report = make_report(report_item(
        entry("carpet"), Status.READY,
        latest=version("26.3", files=(file_info("carpet-26.3.jar", primary=True),
                                      file_info("carpet-26.3-sources.jar")))))
    assert prepare_download(report, tmp_path).extra_files == 1


def test_prepare_detects_conflicts_without_writing(tmp_path: Path) -> None:
    """同名冲突只判断不写盘；目标目录里没有的东西不会被创建。"""
    (tmp_path / "carpet-26.3.jar").write_bytes(b"old")
    prep = prepare_download(sample_report(), tmp_path)
    assert [item.target.name for item in prep.conflicts] == ["carpet-26.3.jar"]
    assert (tmp_path / "carpet-26.3.jar").read_bytes() == b"old"
    assert not (tmp_path / "lithium-26.1.jar").exists()


def test_overwrite_all_maps_conflict_names(tmp_path: Path) -> None:
    """a / k 的语义：一次决定覆盖或跳过全部冲突项。"""
    (tmp_path / "carpet-26.3.jar").write_bytes(b"old")
    prep = prepare_download(sample_report(), tmp_path)
    assert prep.overwrite_all(True) == {"carpet-26.3.jar": True}
    assert prep.overwrite_all(False) == {"carpet-26.3.jar": False}


def test_prepare_does_not_print_anything(tmp_path: Path, capsys) -> None:
    """流程层不打印任何东西（GUI 复用全靠这条）。"""
    prepare_download(sample_report(), tmp_path)
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------- 下载（run_download_flow）
# ---------------------------------------------------------------- 端到端（真 HttpClient）
def real_client(transport):
    """真的 HttpClient.download + 假 stream transport（不联网，其余全是真的）。"""
    from test_http_download import CountingLimiter

    return HttpClient(HttpConfig(rate_limit_per_min=100000), limiter=CountingLimiter(),
                      stream_transport=transport)


def test_flow_with_real_http_client_writes_verified_file(tmp_path: Path) -> None:
    """整条链：prepare -> download_all -> HttpClient.download（.part + sha1 校验 + os.replace）。

    这条用例是"接口对不上"的守门员：流程用假 fetcher、http 用假 transport，
    两边各自全绿也可能在**接缝处**对不上（参数名、返回值、期望的字段）。
    """
    payload = b"REAL-STACK" * 512
    digest = hashlib.sha1(payload).hexdigest()
    report = make_report(report_item(
        entry("carpet"), Status.READY,
        latest=version("26.3", files=(file_info("carpet-26.3.jar", primary=True,
                                                size=len(payload), sha1=digest),))))
    from test_http_download import FakeStreamTransport, make_stream

    prep = prepare_download(report, tmp_path)
    client = real_client(FakeStreamTransport(make_stream(payload, size=64)))
    outcome = run_download_flow(prep, client, sleep=no_sleep)
    assert outcome.summary.ok == 1 and outcome.summary.failed == 0
    assert (tmp_path / "carpet-26.3.jar").read_bytes() == payload
    assert not list(tmp_path.glob("*.part"))
    assert client.stats[0] == 1                     # 下载计入请求数（D45）


def test_flow_with_real_http_client_sha1_mismatch_retries_and_fails(tmp_path: Path) -> None:
    """sha1 不符：重试 2 次（一共 3 次请求）、坏文件删掉、状态 verify_failed。"""
    payload = b"corrupted" * 100
    wrong = hashlib.sha1(b"what-the-server-promised").hexdigest()
    report = make_report(report_item(
        entry("carpet"), Status.READY,
        latest=version("26.3", files=(file_info("carpet-26.3.jar", primary=True,
                                                size=len(payload), sha1=wrong),))))
    from test_http_download import FakeStreamTransport, make_stream

    transport = FakeStreamTransport(make_stream(payload, size=32))
    prep = prepare_download(report, tmp_path)
    client = real_client(transport)
    outcome = run_download_flow(prep, client, sleep=no_sleep)
    assert transport.count == 3                      # retries=2 -> 3 次尝试
    assert outcome.report.items[0].status == STATUS_VERIFY_FAILED
    assert outcome.summary.failure_rows[0][:2] == ("carpet-26.3.jar", "download.error.verify")
    assert not (tmp_path / "carpet-26.3.jar").exists()
    assert not list(tmp_path.glob("*.part"))


def test_run_download_flow_ok(tmp_path: Path) -> None:
    """正常一轮：三个文件下好，汇总数字自洽，没有残留 .part。"""
    prep = prepare_download(sample_report(), tmp_path)
    fetcher = FakeFetcher(payload=b"x" * 10)
    outcome = run_download_flow(prep, fetcher, sleep=no_sleep)
    summary = outcome.summary
    assert (summary.ok, summary.skipped, summary.failed, summary.cancelled) == (2, 0, 0, False)
    assert summary.total == 2 and summary.bytes_total == 20
    assert summary.megabytes == pytest.approx(20 / 1024 / 1024)
    assert sorted(item.target.name for item in summary.ok_items) == ["carpet-26.3.jar",
                                                                    "lithium-26.1.jar"]
    assert summary.target_dir == tmp_path
    assert not list(tmp_path.glob("*.part"))
    assert outcome.report.ok == 2


def test_run_download_flow_empty_plan(tmp_path: Path) -> None:
    """一个模组都没得下：全 0，一个请求都不发。"""
    prep = prepare_download(make_report(report_item(entry("c"), Status.BLOCKED)), tmp_path)
    fetcher = FakeFetcher()
    outcome = run_download_flow(prep, fetcher, sleep=no_sleep)
    assert prep.has_work is False
    assert fetcher.calls == []
    assert (outcome.summary.ok, outcome.summary.total) == (0, 0)
    assert outcome.summary.all_failed is False          # 没东西可下 != 全失败


def test_run_download_flow_skips_user_choice(tmp_path: Path) -> None:
    """overwrite=False 的条目直接跳过：不发请求、不写盘，汇总里列进"跳过"。"""
    (tmp_path / "carpet-26.3.jar").write_bytes(b"keep-me")
    prep = prepare_download(sample_report(), tmp_path)
    fetcher = FakeFetcher()
    outcome = run_download_flow(prep, fetcher, overwrite={"carpet-26.3.jar": False},
                                sleep=no_sleep)
    assert fetcher.calls == ["lithium-26.1.jar"]
    assert (tmp_path / "carpet-26.3.jar").read_bytes() == b"keep-me"
    assert outcome.summary.skipped_names == ("carpet-26.3.jar",)
    assert outcome.summary.skipped_items[0].message_key == "download.skip.user"
    assert (outcome.summary.ok, outcome.summary.skipped) == (1, 1)
    # sample_report 里还有一个"没有可下载 .jar"的 jei，它也算跳过（自洽性见下一个用例）
    assert outcome.summary.skipped_rows == (("carpet-26.3.jar", "download.skip.user"),
                                            ("jei", "download.skip.no_jar"))
    # 汇总行的数字必须加得起来（主 Agent 裁决 4）
    assert outcome.summary.outcome_total == (outcome.summary.ok + outcome.summary.skipped_total
                                             + outcome.summary.failed)


def test_run_download_flow_disk_write_failure_is_isolated(tmp_path: Path) -> None:
    """磁盘满 / 没有权限：该文件失败、其余照下，已下好的不删（§14.5 第 6 条）。"""
    prep = prepare_download(sample_report(), tmp_path)
    # 只有 carpet 写不进去（模拟磁盘满 / 没有权限），lithium 必须照下不误
    fetcher = FakeFetcher(error=OSError(28, "disk full"), fail_names=("carpet-26.3.jar",))
    outcome = run_download_flow(prep, fetcher, sleep=no_sleep)
    assert (outcome.summary.ok, outcome.summary.failed) == (1, 1)
    assert outcome.summary.failure_rows[0][:2] == ("carpet-26.3.jar", "download.error.write")
    assert (tmp_path / "lithium-26.1.jar").exists()
    assert not (tmp_path / "carpet-26.3.jar").exists()


def test_run_download_flow_retries_then_gives_up(tmp_path: Path) -> None:
    """重试耗尽：retries=2 -> 一共 3 次尝试，退避 1s / 2s，最后记失败。"""
    prep = prepare_download(one_ready_report(), tmp_path)
    fetcher = FakeFetcher(fail_times=99)
    sleeps: list[float] = []
    outcome = run_download_flow(prep, fetcher, sleep=sleeps.append)
    assert len(fetcher.calls) == 3
    assert sleeps == [1.0, 2.0]
    assert outcome.summary.failed == 1 and outcome.summary.retries == 2
    assert outcome.report.items[0].status == STATUS_FAILED


def test_run_download_flow_verify_failure_is_reported_as_such(tmp_path: Path) -> None:
    """sha1 不符：状态 verify_failed，原因 key 是"校验失败（文件损坏，已删除）"。"""
    prep = prepare_download(one_ready_report(), tmp_path)
    outcome = run_download_flow(prep, FakeFetcher(verify_times=99), sleep=no_sleep)
    assert outcome.report.items[0].status == STATUS_VERIFY_FAILED
    assert outcome.summary.failed == 1
    rows = outcome.summary.failure_rows
    assert [row[:2] for row in rows] == [("carpet-26.3.jar", "download.error.verify")]
    assert rows[0][2]                     # 具体原因要带上，否则用户看到的是空括号


def test_run_download_flow_404_is_network_failure(tmp_path: Path) -> None:
    """404（直链拿不到）：记网络失败，不影响其它文件。"""
    prep = prepare_download(sample_report(), tmp_path)
    fetcher = FakeFetcher(error=ProviderHTTPError("not found", status=404, url="u"),
                          fail_names=("carpet-26.3.jar",))
    outcome = run_download_flow(prep, fetcher, retries=0, sleep=no_sleep)
    assert ("carpet-26.3.jar", "download.error.net") in [row[:2]
                                                          for row in outcome.summary.failure_rows]
    assert outcome.summary.ok == 1
    assert (tmp_path / "lithium-26.1.jar").exists()


def test_run_download_flow_429_not_counted_as_retry(tmp_path: Path) -> None:
    """429 不计入重试：retries=0 也能靠限流放行成功（§14.3）。"""
    prep = prepare_download(one_ready_report(), tmp_path)
    fetcher = FakeFetcher(rate_limit_times=2)
    sleeps: list[float] = []
    outcome = run_download_flow(prep, fetcher, retries=0, sleep=sleeps.append)
    assert outcome.summary.ok == 1 and len(fetcher.calls) == 3 and sleeps == []


def test_run_download_flow_no_jar_entries_counted_as_skipped(tmp_path: Path) -> None:
    """没有可下载 .jar 的模组归到**跳过**里，且带原因（主 Agent 裁决 4）。

    归到失败会让"汇总行说失败 1 个、失败清单却列 2 条" —— 用户会以为程序算错了。
    """
    report = make_report(
        report_item(entry("carpet"), Status.READY,
                    latest=version("26.3", files=(file_info("carpet-26.3.jar", primary=True),))),
        report_item(entry("jei"), Status.READY,
                    latest=version("26.3", files=(file_info("jei-26.3-sources.jar",
                                                            primary=True),))),
    )
    outcome = run_download_flow(prepare_download(report, tmp_path), FakeFetcher(),
                                sleep=no_sleep)
    summary = outcome.summary
    assert ("jei", SKIP_NO_JAR) in summary.skipped_rows   # 条目没有 file_name 时用显示名
    assert summary.failed == 0 and summary.failure_rows == ()
    assert summary.skipped_total == 1 and summary.skipped == 0
    assert summary.outcome_total == 2                     # 两个 🟢 条目都进汇总分母
    assert summary.outcome_total == summary.ok + summary.skipped_total + summary.failed


def test_run_download_flow_all_failed_flag(tmp_path: Path) -> None:
    """全部失败 -> all_failed=True（汇总屏要追加"先检查代理"那句）。"""
    prep = prepare_download(sample_report(), tmp_path)
    outcome = run_download_flow(prep, FakeFetcher(fail_times=99), sleep=no_sleep)
    assert outcome.summary.all_failed is True


# ---------------------------------------------------------------- 取消
def test_run_download_flow_should_stop_probe_cancels(tmp_path: Path) -> None:
    """should_stop 探针为真：停止派发、删掉残留 .part、已下好的保留。"""
    prep = prepare_download(sample_report(), tmp_path)
    left_part = tmp_path / "lithium-26.1.jar.part"
    left_part.write_bytes(b"half")
    fetcher = FakeFetcher(on_call=lambda index: None)
    outcome = run_download_flow(prep, fetcher, jobs=1, sleep=no_sleep,
                                should_stop=lambda: len(fetcher.calls) >= 1)
    assert outcome.summary.cancelled is True
    assert fetcher.calls == ["lithium-26.1.jar"]        # 只发了第一个就停了
    assert (tmp_path / "lithium-26.1.jar").exists()
    assert not left_part.exists()
    assert not (tmp_path / "carpet-26.3.jar").exists()
    assert outcome.report.items[1].status == STATUS_CANCELLED


def test_run_download_flow_cancel_event_cancels(tmp_path: Path) -> None:
    """cancel 事件（GUI 用）与探针等效：任一为真就停。"""
    prep = prepare_download(sample_report(), tmp_path)
    event = threading.Event()
    event.set()
    outcome = run_download_flow(prep, FakeFetcher(), cancel=event, sleep=no_sleep)
    assert outcome.summary.cancelled is True
    assert outcome.summary.ok == 0 and outcome.summary.all_failed is False


def test_run_download_flow_cancel_and_probe_combined(tmp_path: Path) -> None:
    """同时给事件与探针：事件为真也停（不是只看探针）。"""
    prep = prepare_download(sample_report(), tmp_path)
    event = threading.Event()
    event.set()
    calls = {"n": 0}

    def probe() -> bool:
        calls["n"] += 1
        return False

    outcome = run_download_flow(prep, FakeFetcher(), cancel=event, should_stop=probe,
                                sleep=no_sleep)
    assert outcome.summary.cancelled is True


# ---------------------------------------------------------------- 回调
def test_run_download_flow_progress_and_item_callbacks(tmp_path: Path) -> None:
    """on_progress 报 (条目, 已下载, 总大小)；on_item 每个文件报一次成功。"""
    prep = prepare_download(sample_report(), tmp_path)
    progress: list[tuple[str, int, int]] = []
    done: list[tuple[str, bool]] = []
    outcome = run_download_flow(
        prep, FakeFetcher(payload=b"x" * 10, delay=0.005), sleep=no_sleep, jobs=2,
        on_progress=lambda item, done_bytes, total: progress.append(
            (item.target.name, done_bytes, total)),
        on_item=lambda item, ok: done.append((item.target.name, ok)))
    assert outcome.summary.ok == 2
    assert {name for name, _done_bytes, _total in progress} == {"carpet-26.3.jar",
                                                                "lithium-26.1.jar"}
    assert all(total == 100 for _n, _d, total in progress if _n == "carpet-26.3.jar")
    assert sorted(done) == [("carpet-26.3.jar", True), ("lithium-26.1.jar", True)]


def test_run_download_flow_item_callback_reports_failure(tmp_path: Path) -> None:
    """on_item 在失败时也报（(条目, False)），渲染方才能把进度对对。"""
    prep = prepare_download(one_ready_report(), tmp_path)
    done: list[tuple[str, bool]] = []
    run_download_flow(prep, FakeFetcher(fail_times=99), retries=0, sleep=no_sleep,
                      on_item=lambda item, ok: done.append((item.target.name, ok)))
    assert done == [("carpet-26.3.jar", False)]


def test_run_download_flow_is_parallel(tmp_path: Path) -> None:
    """jobs=3 真的并发（GUI/CLI 的进度行依赖这一点）。"""
    prep = prepare_download(sample_report(), tmp_path)
    fetcher = FakeFetcher(delay=0.05)
    run_download_flow(prep, fetcher, sleep=no_sleep)
    assert fetcher.max_live == 2                  # 计划里只有 2 个文件


def test_run_download_flow_does_not_print(tmp_path: Path, capsys) -> None:
    """整条流程不打印任何东西。"""
    prep = prepare_download(sample_report(), tmp_path)
    run_download_flow(prep, FakeFetcher(), sleep=no_sleep)
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------- 目标文件夹预检查
def test_check_target_dir_ok(tmp_path: Path) -> None:
    """正常目录：ok，给出剩余空间。"""
    check = check_target_dir(tmp_path)
    assert check.ok is True and check.problem_key == ""
    assert check.free_bytes > 0
    assert check.low_space is False


def test_check_target_dir_missing_and_is_file(tmp_path: Path) -> None:
    """不存在 -> missing（要问用户建不建）；是文件 -> is_file（✗）。"""
    missing = check_target_dir(tmp_path / "nope")
    assert (missing.ok, missing.problem_key) == (False, TARGET_MISSING)
    assert not (tmp_path / "nope").exists()            # 检查不创建目录
    target = tmp_path / "afile"
    target.write_bytes(b"x")
    assert check_target_dir(target).problem_key == TARGET_IS_FILE


def test_check_target_dir_not_writable(tmp_path: Path, monkeypatch) -> None:
    """写不进去 -> not_writable（✗ 请换一个文件夹）。"""
    import tempfile as tempfile_module

    def refuse(*args, **kwargs):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(tempfile_module, "mkstemp", refuse)
    check = check_target_dir(tmp_path)
    assert (check.ok, check.problem_key) == (False, TARGET_NOT_WRITABLE)


def test_check_target_dir_low_space(tmp_path: Path, monkeypatch) -> None:
    """剩余空间 < 需要 × 1.1 -> low_space（提醒后可继续，不是错误）。"""
    import shutil as shutil_module
    from collections import namedtuple

    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil_module, "disk_usage", lambda _p: usage(0, 0, 100))
    assert check_target_dir(tmp_path, needed_bytes=95).low_space is True    # 100 < 95 × 1.1
    assert check_target_dir(tmp_path, needed_bytes=90).low_space is False   # 100 > 99
    assert check_target_dir(tmp_path, needed_bytes=50).low_space is False
    assert check_target_dir(tmp_path, needed_bytes=0).low_space is False


def test_check_target_dir_unknown_free_space(tmp_path: Path, monkeypatch) -> None:
    """量不出剩余空间时给 UNKNOWN_FREE，并且**不**提醒（绝不因为量不出来就拦人）。"""
    import shutil as shutil_module

    def boom(_path):
        raise OSError("nope")

    monkeypatch.setattr(shutil_module, "disk_usage", boom)
    check = check_target_dir(tmp_path, needed_bytes=10 ** 9)
    assert (check.ok, check.free_bytes, check.low_space) == (True, UNKNOWN_FREE, False)


def test_check_target_dir_flags_mods_folder(tmp_path: Path) -> None:
    """选到 mods 文件夹 / .minecraft：允许，但要提醒（§14.5 第 14 条）。"""
    mods = tmp_path / "mods"
    mods.mkdir()
    assert check_target_dir(mods).looks_like_mods is True
    mc = tmp_path / ".minecraft" / "downloads"
    mc.mkdir(parents=True)
    assert check_target_dir(mc).looks_like_mods is True
    plain = tmp_path / "downloads"
    plain.mkdir()
    assert check_target_dir(plain).looks_like_mods is False


def test_looks_like_mods_dir_cases() -> None:
    """大小写与路径段都要认。"""
    assert looks_like_mods_dir(Path("/srv/mods")) is True
    assert looks_like_mods_dir(Path("/srv/MODS")) is True
    assert looks_like_mods_dir(Path.home() / ".minecraft" / "mods") is True
    assert looks_like_mods_dir(Path("/srv/downloads")) is False


def test_ensure_target_dir(tmp_path: Path, monkeypatch) -> None:
    """创建目录（含多级）；失败返回 False，不抛异常。"""
    target = tmp_path / "a" / "b" / "c"
    assert ensure_target_dir(target) is True and target.is_dir()
    assert ensure_target_dir(target) is True               # 幂等

    def refuse(self, *args, **kwargs):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(Path, "mkdir", refuse)
    assert ensure_target_dir(tmp_path / "no" / "way") is False


def test_summary_reports_small_numbers(tmp_path: Path) -> None:
    """汇总的数字自洽：ok + skipped(全部) + failed == outcome_total。"""
    prep = prepare_download(sample_report(), tmp_path)
    outcome = run_download_flow(prep, FakeFetcher(payload=b"y" * 7), sleep=no_sleep)
    summary = outcome.summary
    cancelled = sum(1 for item in outcome.report.items if item.status == STATUS_CANCELLED)
    assert summary.ok + summary.skipped + summary.failed + cancelled == summary.total
    assert summary.outcome_total == (summary.ok + summary.skipped_total + summary.failed)
    assert summary.bytes_total == 14
    assert summary.elapsed >= 0.0
    assert summary.retries == 2


def test_summary_numbers_add_up_with_every_skip_kind(tmp_path: Path) -> None:
    """三类跳过混在一起时，汇总行的数字仍然加得起来（主 Agent 裁决 4 的核心）。"""
    report = make_report(
        # 🟢 能下（但用户选择跳过）
        report_item(entry("carpet"), Status.READY,
                    latest=version("26.3", files=(file_info("carpet-26.3.jar", primary=True),))),
        # 🟢 能下（照常下载）
        report_item(entry("sodium"), Status.READY,
                    latest=version("26.3", files=(file_info("sodium-26.3.jar", primary=True),))),
        # 🟢 没有可下载的 .jar
        report_item(entry("jei"), Status.READY,
                    latest=version("26.3", files=(file_info("jei-26.3-sources.jar",
                                                            primary=True),))),
        # 🟡 没有「可用」版本
        report_item(entry("old"), Status.DEGRADED, latest=version("26.3")),
    )
    prep = prepare_download(report, tmp_path)
    outcome = run_download_flow(prep, FakeFetcher(), overwrite={"carpet-26.3.jar": False},
                                sleep=no_sleep)
    summary = outcome.summary
    assert (summary.ok, summary.skipped, summary.failed) == (1, 1, 0)
    assert summary.skipped_total == 3                     # 用户跳过 + 无 jar + 无版本
    assert summary.outcome_total == 4                     # 4 个条目都进了汇总
    assert summary.outcome_total == (summary.ok + summary.skipped_total + summary.failed)
    assert len({name for name, _key in summary.skipped_rows}) == 3   # 三条都列出来
