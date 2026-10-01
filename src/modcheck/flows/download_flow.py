"""download 流程：选品 -> 同名冲突 -> 下载 -> 汇总（PRD §14，R3-B04 ~ R3-B12）。

本模块是「流程」层：**不打印任何东西、不问任何问题、不决定屏幕上写什么**。
它只做两件事：

    ① 把"一次检查的报告"变成"一份下载计划 + 需要用户拍板的东西"（选品、同名冲突）；
    ② 把计划跑成结果（并发、重试、取消、进度），并给出**汇总要用的数据**。

CLI 与 GUI 共用同一条流水线，各自负责"问"与"画"：

    prep = prepare_download(report, target_dir)      # 不写盘、不询问
    ...问用户（同名冲突 / 确认开跑 / 目标文件夹）...
    outcome = run_download_flow(prep, client, overwrite=..., on_progress=...)
    outcome.summary                                   # 汇总屏的数字、条目、原因 key

为什么下载逻辑不能写进 cli/（PRD §14.6 第 6 条）：GUI 三期要用同一份，
两份实现迟早漂移 —— 表现就是"同一个 bug 只在一边复现"。
"""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Final, Mapping, Sequence

from modcheck.core.downloader import (SKIP_NO_JAR, SKIP_NO_VERSION, STATUS_FAILED, STATUS_OK,
                                      STATUS_SKIPPED, STATUS_VERIFY_FAILED, DownloadItem,
                                      DownloadPlan, DownloadReport, conflicts, download_all,
                                      extra_files_count, overwrite_key, plan_for)
from modcheck.core.models import ModEntry
from modcheck.core.report import Report

#: 同时下载几个文件（PRD §14.3：3 = 不把带宽打满、也不容易触发 CDN 侧限制）
DEFAULT_JOBS: Final[int] = 3
#: 每个文件失败重试几次（PRD §14.5 第 7 条：退避 1s / 2s，由 download_all 执行）
DEFAULT_RETRIES: Final[int] = 2
#: 空间预检查的余量（PRD §14.5 第 16 条：剩余空间 < 总大小 × 1.1 才提醒）
SPACE_MARGIN: Final[float] = 1.1
#: disk_usage 拿不到时的哨兵（不提醒，绝不因为量不出来就拦住用户）
UNKNOWN_FREE: Final[int] = -1

#: 目标文件夹预检查的问题 key（文案由调用方渲染）
TARGET_MISSING: Final[str] = "download.target.missing"
TARGET_IS_FILE: Final[str] = "download.target.is_file"
TARGET_NOT_WRITABLE: Final[str] = "download.target.not_writable"

#: 进度回调：(条目, 已下载字节, 该文件总字节)；由调用方节流
ProgressFn = Callable[[DownloadItem, int, int], None]
#: 每个文件**这一次尝试**结束时的回调：(条目, 是否成功)。
#: 有重试时同一个文件可能回调多次（渲染方据此打"每完成一个文件一行"）。
ItemFn = Callable[[DownloadItem, bool], None]
#: 取消探针：返回 True 表示调用方要求停下（与 check/scan 流程同一风格）
StopFn = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class DownloadPrep:
    """下载前的准备结果：计划 + 冲突 + 汇总要用到的附加信息。

    这里**只读不写**：plan_for 只拼路径，conflicts 只 stat 目标文件。
    """

    plan: DownloadPlan
    target_dir: Path
    #: 目标目录里已经存在同名文件的条目（逐个问用户 o/s/a/k/q）
    conflicts: tuple[DownloadItem, ...]
    #: 有几个模组除主文件还有附加文件（源码/文档），汇总里的 ℹ 行用
    extra_files: int
    #: 该版本一个可下载的 .jar 都没有（PRD §14.5 第 2 条：要在失败清单里列出）
    no_jar: tuple[ModEntry, ...]
    #: 🟡 但没有"可用"版本可下（PRD §14.5 第 17 条：标注在汇总里）
    no_version: tuple[ModEntry, ...]

    @property
    def items(self) -> tuple[DownloadItem, ...]:
        """要下载的文件（按报告分组顺序）。"""
        return self.plan.items

    @property
    def total(self) -> int:
        """文件数。"""
        return len(self.plan.items)

    @property
    def has_work(self) -> bool:
        """有没有文件要下；False 时调用方**直接给结论**，不弹文件夹选择（§14.5 第 12 条）。"""
        return bool(self.plan.items)

    @property
    def total_bytes(self) -> int:
        """计划里全部文件的大小合计（空间预检查用；数据源没给大小时按 0 算）。"""
        return sum(int(item.file.size or 0) for item in self.plan.items)

    def overwrite_all(self, value: bool) -> dict[str, bool]:
        """把"后面的全部覆盖 / 全部跳过"（a / k）变成 download_all 认的映射。"""
        return {overwrite_key(item): value for item in self.conflicts}


@dataclass(frozen=True, slots=True)
class DownloadSummary:
    """下载结果的汇总：汇总屏要用到的**全部**数字、条目与原因 key。"""

    target_dir: Path
    total: int
    ok: int
    skipped: int
    failed: int
    bytes_total: int
    elapsed: float
    cancelled: bool
    extra_files: int
    #: 每个文件最多重试了几次（失败行要写"已重试 2 次"）
    retries: int = 0
    ok_items: tuple[DownloadItem, ...] = ()
    skipped_items: tuple[DownloadItem, ...] = ()
    failed_items: tuple[DownloadItem, ...] = ()
    no_jar: tuple[ModEntry, ...] = ()

    @property
    def megabytes(self) -> float:
        """下载总量（MB）。"""
        return self.bytes_total / (1024 * 1024)

    @property
    def all_failed(self) -> bool:
        """一个都没成功（汇总屏要追加"先检查代理设置"那句）。"""
        return self.total > 0 and self.ok == 0 and not self.cancelled

    @property
    def failure_rows(self) -> tuple[tuple[str, str, str], ...]:
        """失败清单的 (文件名, 原因 key, 具体原因)。

        具体原因（detail）只有"网络失败"那条文案用得上（"下载失败（{detail}）"），
        其它原因 key 自带完整句子，多传一个参数不会影响格式化。

        PRD §14.5 第 2 条要求"没有可下载的 .jar"的模组也列在失败清单里，
        所以这里把它和正式失败条目合并给出 —— 渲染方不必自己拼。
        """
        rows = [(item.target.name, item.message_key or "download.error.net", item.detail)
                for item in self.failed_items]
        rows += [((entry.file_name or entry.best_name or entry.key), SKIP_NO_JAR, "")
                 for entry in self.no_jar]
        return tuple(rows)

    @property
    def skipped_names(self) -> tuple[str, ...]:
        """用户选择跳过的文件名（汇总的 ⏭ 行）。"""
        return tuple(item.target.name for item in self.skipped_items)


@dataclass(frozen=True, slots=True)
class DownloadOutcome:
    """一次下载的完整结果：计划 + 原始结果 + 汇总。"""

    prep: DownloadPrep
    report: DownloadReport
    summary: DownloadSummary


@dataclass(frozen=True, slots=True)
class TargetCheck:
    """目标文件夹的预检查结果（PRD §14.5 第 10 / 11 / 14 / 16 条）。"""

    ok: bool
    #: 不能下载时的原因 key（TARGET_MISSING / TARGET_IS_FILE / TARGET_NOT_WRITABLE）
    problem_key: str = ""
    #: 剩余空间（字节；UNKNOWN_FREE 表示量不出来）
    free_bytes: int = UNKNOWN_FREE
    needed_bytes: int = 0
    #: 剩余空间不够（提醒后用户仍可继续）
    low_space: bool = False
    #: 看起来像正在使用的 mods 文件夹（允许，但要先提醒一次）
    looks_like_mods: bool = False


def plan_skips(plan: DownloadPlan, reason_key: str) -> tuple[ModEntry, ...]:
    """按原因 key 取出计划里被跳过的条目（保持报告顺序）。"""
    return tuple(entry for entry, key in plan.skipped if key == reason_key)


def prepare_download(report: Report, target_dir: Path) -> DownloadPrep:
    """选品 + 找同名冲突（PRD §14.1 / §14.2）。**不写盘、不询问、不创建目录**。

    参数：
        report: 一次检查的报告（🟢 取最新版、🟡 取「可用」的旧稳定版）。
        target_dir: 下载目标目录（只用来拼路径）。
    返回：
        DownloadPrep；要问用户的东西（conflicts）都在里面。
    """
    root = Path(target_dir)
    plan = plan_for(report, root)
    return DownloadPrep(plan=plan, target_dir=root, conflicts=conflicts(plan),
                        extra_files=extra_files_count(plan),
                        no_jar=plan_skips(plan, SKIP_NO_JAR),
                        no_version=plan_skips(plan, SKIP_NO_VERSION))


def run_download_flow(prep: DownloadPrep, fetcher, *,
                      overwrite: Mapping[str, bool] | None = None,
                      on_progress: ProgressFn | None = None,
                      on_item: ItemFn | None = None,
                      should_stop: StopFn | None = None,
                      cancel: threading.Event | None = None,
                      jobs: int = DEFAULT_JOBS, retries: int = DEFAULT_RETRIES,
                      sleep: Callable[[float], None] | None = None) -> DownloadOutcome:
    """跑完一次下载，返回 DownloadOutcome（原始结果 + 汇总）。

    参数：
        prep: prepare_download 的结果。
        fetcher: 实现 download(url, dest, *, sha1, on_chunk, timeout) -> int 的对象
            （CLI/GUI 注入 HttpClient；测试注入假 fetcher）。
        overwrite: 目标文件名 -> 是否覆盖；False 表示用户选择跳过（默认全部覆盖）。
        on_progress: 进度回调（调用方负责节流）。
        on_item: 每个文件每一次尝试结束时的回调 (条目, 是否成功)。
        should_stop: 取消探针（与 check/scan 流程一致）；置真后停止派发新任务、
            删掉残留 .part，已下好的文件保留。
        cancel: 取消事件（GUI 用事件更方便）；与 should_stop **任一为真**就停。
        jobs / retries: 并发数与每文件重试次数。
        sleep: 注入的睡眠函数（测试用；默认 time.sleep）。

    返回：
        DownloadOutcome；prep.total == summary.ok + skipped + 未完成，cancelled 时见 report。
    """
    plan = prep.plan
    events = _ItemWatcher(plan.items, on_item) if on_item is not None else None
    runner = _ReportingFetcher(fetcher, events) if events is not None else fetcher
    report = download_all(plan, runner, overwrite=overwrite, on_progress=on_progress,
                          cancel=_cancel_flag(cancel, should_stop), retries=retries,
                          jobs=jobs, sleep=sleep)
    return DownloadOutcome(prep=prep, report=report,
                           summary=_summarize(prep, report, retries=retries))


def check_target_dir(target_dir: Path, needed_bytes: int = 0) -> TargetCheck:
    """检查目标文件夹能不能下载（PRD §14.5 第 10 / 11 / 14 / 16 条）。

    **什么都不创建、什么都不修改**：目录不存在只是"要问用户建不建"，
    不是错误；真正写不进去才是错误。
    """
    target = Path(target_dir)
    if target.exists() and not target.is_dir():
        return TargetCheck(ok=False, problem_key=TARGET_IS_FILE)
    if not target.is_dir():
        return TargetCheck(ok=False, problem_key=TARGET_MISSING)
    if not _probe_writable(target):
        return TargetCheck(ok=False, problem_key=TARGET_NOT_WRITABLE)
    free = UNKNOWN_FREE
    try:
        free = int(shutil.disk_usage(target).free)
    except OSError:
        free = UNKNOWN_FREE
    low = needed_bytes > 0 and 0 <= free < int(needed_bytes * SPACE_MARGIN)
    return TargetCheck(ok=True, free_bytes=free, needed_bytes=int(needed_bytes), low_space=low,
                       looks_like_mods=looks_like_mods_dir(target))


def ensure_target_dir(target_dir: Path) -> bool:
    """按用户确认创建目标文件夹；失败返回 False（文案由调用方给）。"""
    try:
        Path(target_dir).mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False


def looks_like_mods_dir(target_dir: Path) -> bool:
    """看起来像"正在使用的 mods 文件夹"（PRD §14.5 第 14 条：允许，但先提醒一次）。

    判据（任一成立）：目录名就叫 mods（大小写不敏感），或路径里出现过 .minecraft。
    """
    target = Path(target_dir)
    if target.name.lower() == "mods":
        return True
    return any(part.lower() == ".minecraft" for part in target.parts)


def _summarize(prep: DownloadPrep, report: DownloadReport, *, retries: int) -> DownloadSummary:
    """把 DownloadReport 折成汇总数据（不渲染、不格式化）。"""
    items = report.items
    return DownloadSummary(
        target_dir=prep.target_dir, total=len(items), ok=report.ok, skipped=report.skipped,
        failed=report.failed, bytes_total=report.bytes_total, elapsed=report.elapsed,
        cancelled=report.cancelled, extra_files=prep.extra_files, retries=retries,
        ok_items=tuple(item for item in items if item.status == STATUS_OK),
        skipped_items=tuple(item for item in items if item.status == STATUS_SKIPPED),
        failed_items=tuple(item for item in items
                           if item.status in (STATUS_FAILED, STATUS_VERIFY_FAILED)),
        no_jar=prep.no_jar)


def _probe_writable(directory: Path) -> bool:
    """真写一个临时文件再删掉（**不创建目录**：目录存不存在由调用方判断）。"""
    try:
        handle, name = tempfile.mkstemp(dir=str(directory), prefix=".modcheck-probe-")
    except OSError:
        return False
    os.close(handle)
    try:
        Path(name).unlink(missing_ok=True)
    except OSError:
        pass
    return True


class _StopFlag:
    """把 should_stop 探针适配成 download_all 认的取消事件（它只要求 is_set()）。

    给 cancel 与 should_stop 时**任一为真**就停：GUI 用事件、CLI 用探针，
    两边共享同一条取消路径。
    """

    def __init__(self, cancel: threading.Event | None, probe: StopFn) -> None:
        self._cancel = cancel
        self._probe = probe

    def is_set(self) -> bool:
        """是否要求停下。"""
        if self._cancel is not None and self._cancel.is_set():
            return True
        return bool(self._probe())


def _cancel_flag(cancel: threading.Event | None, should_stop: StopFn | None):
    """组装传给 download_all 的取消标志。"""
    if should_stop is None:
        return cancel
    return _StopFlag(cancel, should_stop)


class _ItemWatcher:
    """按目标路径把"一个文件下完了"对应回计划条目。

    同一个目标文件名可能对应多个条目（两个模组的主文件重名），
    所以按先后顺序取；取不到就不报 —— 宁可少报一行，也不能报错文件。
    """

    def __init__(self, items: Sequence[DownloadItem], on_item: ItemFn) -> None:
        self._queue: dict[str, list[DownloadItem]] = {}
        for item in items:
            self._queue.setdefault(str(item.target), []).append(item)
        self._on_item = on_item
        self._lock = threading.Lock()

    def notify(self, dest, ok: bool) -> None:
        """通知"这个目标文件这一次尝试结束了"。"""
        with self._lock:
            queue = self._queue.get(str(Path(dest)))
            item = queue.pop(0) if queue else None
        if item is not None:
            self._on_item(item, ok)


class _ReportingFetcher:
    """给 fetcher 包一层，把"每个文件下完了"报给 watcher。

    download_all 只在**全部结束后**返回结果，而"非 TTY 每完成一个文件打一行"
    与 GUI 的逐行状态都需要边下边报，所以在这一层观察（URL/目标文件是可用的）。
    """

    def __init__(self, fetcher, watcher: _ItemWatcher) -> None:
        self._fetcher = fetcher
        self._watcher = watcher

    def download(self, url: str, dest: Path, *, sha1: str | None = None,
                 on_chunk: Callable[[int], None] | None = None,
                 timeout: float | None = None) -> int:
        """转发给真 fetcher，并报告这一次尝试的结果。"""
        try:
            written = self._fetcher.download(url, dest, sha1=sha1, on_chunk=on_chunk,
                                             timeout=timeout)
        except BaseException:            # noqa: BLE001 - 只做观察，异常必须原样抛回
            self._watcher.notify(dest, False)
            raise
        self._watcher.notify(dest, True)
        return written


__all__ = ["DEFAULT_JOBS", "DEFAULT_RETRIES", "SPACE_MARGIN", "TARGET_IS_FILE",
           "TARGET_MISSING", "TARGET_NOT_WRITABLE", "UNKNOWN_FREE", "DownloadOutcome",
           "DownloadPrep", "DownloadSummary", "ItemFn", "ProgressFn", "StopFn", "TargetCheck",
           "check_target_dir", "ensure_target_dir", "looks_like_mods_dir", "plan_skips",
           "prepare_download", "run_download_flow"]
