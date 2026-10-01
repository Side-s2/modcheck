"""下载计划的纯逻辑（PRD §14.1 / §14.2，R3-B02 / R3-B03）。

分层约束（PRD §14.2）：
  * 不 print / 不 input / 不 sys.exit、不 import providers / 不直接联网；
  * 真正落盘只发生在 download_all 注入的 fetcher（HttpClient.download）里；
  * 所有业务规则都在这里，CLI 只负责屏幕与编排（GUI 复用全靠这条）。

下载范围（PRD §14.1，裁决 D49）：
  🟢 就绪   -> latest_for_loader（目标加载器的最新正式版）
  🟡 需注意 -> latest_compat（「可用：」那一行的旧稳定版）
  🔴 / 🟠 / ⚪ / ⚫ 一律跳过；只下 primary 主文件。
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Final, Mapping, Sequence

from modcheck.core.models import FileInfo, ModEntry, Status, VersionInfo
from modcheck.core.report import Report, ReportItem
from modcheck.errors import (ModcheckError, ProviderError, ProviderRateLimited,
                             ProviderVerifyError)

#: 允许下载的两组（PRD §14.1）
DOWNLOADABLE: Final[tuple[Status, ...]] = (Status.READY, Status.DEGRADED)

#: Windows 文件名非法字符（chr(34)=双引号、chr(92)=反斜杠）
ILLEGAL_CHARS: Final[str] = "/" + ":" + "*" + "?" + chr(34) + "<" + ">" + "|" + chr(92)
#: 非法字符的替换目标（PRD §14.5 第 4 条）
REPLACEMENT: Final[str] = "_"
#: 文件名最大长度（PRD §14.2，含 .jar 后缀）
MAX_FILENAME: Final[int] = 200
#: 空名兜底用的后缀
JAR_SUFFIX: Final[str] = ".jar"
#: 明显不是模组主文件的附加 jar 后缀（主 Agent 裁决；sources/javadoc 对服主无用）
ADDON_SUFFIXES: Final[tuple[str, ...]] = ("-sources", "-javadoc", "-dev", "-api")
#: 临时文件后缀（先写 .part 再原子改名；与 HttpClient.download 必须一致）
PART_SUFFIX: Final[str] = ".part"

#: 下载状态取值（PRD §14.2 的 DownloadItem.status）
STATUS_PENDING: Final[str] = "pending"
STATUS_OK: Final[str] = "ok"
STATUS_SKIPPED: Final[str] = "skipped"
STATUS_FAILED: Final[str] = "failed"
STATUS_VERIFY_FAILED: Final[str] = "verify_failed"
STATUS_CANCELLED: Final[str] = "cancelled"


@dataclass(frozen=True, slots=True)
class DownloadItem:
    """一个待下载文件。"""

    entry: ModEntry
    version: VersionInfo
    file: FileInfo
    target: Path
    status: str = STATUS_PENDING
    message_key: str = ""
    #: 失败的具体原因（领域异常的中文说明）。渲染方把它填进"下载失败（{detail}）"，
    #: 否则用户只看到"下载失败（）"—— 排查时最需要的那句话反而没了。
    detail: str = ""
    bytes_done: int = 0


@dataclass(frozen=True, slots=True)
class DownloadPlan:
    """一次下载计划。"""

    items: tuple[DownloadItem, ...]
    skipped: tuple[tuple[ModEntry, str], ...]


@dataclass(frozen=True, slots=True)
class DownloadReport:
    """一次下载的结果汇总。"""

    items: tuple[DownloadItem, ...]
    ok: int
    skipped: int
    failed: int
    bytes_total: int
    elapsed: float
    cancelled: bool


def pick_version(item: ReportItem) -> VersionInfo | None:
    """按组挑要下载的版本：🟢 取最新版，🟡 取「可用」的那个旧稳定版。"""
    if item.status is Status.READY:
        return item.latest_for_loader
    if item.status is Status.DEGRADED:
        return item.latest_compat
    return None


def is_jar_file(item: FileInfo) -> bool:
    """是否算「可下载的模组主文件」。

    两条规则（主 Agent 裁决，覆盖 PRD §14.2 与 §14.5 第 2 条的字面冲突）：
      1. 附加 jar 一律排除：文件名在 .jar 之前以 -sources / -javadoc / -dev / -api 结尾的，
         是源码包/文档包/开发包，放进 mods 文件夹不会被加载 —— 下给用户比不下更糟；
      2. filename 为空的 primary 仍然算：§14.5 第 3 条要求用
         {slug}-{version_number}.jar 兜底，而不是把它当成"没有 jar"跳过。
    """
    name = (item.filename or "").strip().lower()
    if not name:
        return bool(item.primary)
    if not name.endswith(JAR_SUFFIX):
        return False
    stem = name[: -len(JAR_SUFFIX)]
    return not stem.endswith(ADDON_SUFFIXES)


def pick_file(version: VersionInfo) -> FileInfo | None:
    """挑主文件：优先 primary 的 .jar，没有就取第一个 .jar，一个都没有返回 None。

    裁决 D49：附加文件（sources / javadoc）不下载。
    """
    jars = [item for item in version.files if is_jar_file(item)]
    if not jars:
        return None
    for item in jars:
        if item.primary:
            return item
    return jars[0]


def part_path(dest: Path) -> Path:
    """下载过程中的临时文件路径（dest + .part）。"""
    target = Path(dest)
    return target.with_name(target.name + PART_SUFFIX)


def fallback_filename(entry: ModEntry, version: VersionInfo) -> str:
    """文件名为空时的兜底名：{slug}-{version_number}.jar（PRD §14.5 第 3 条）。"""
    slug = ""
    for value in (entry.sources or {}).values():
        if value:
            slug = str(value)
            break
    base = slug or entry.mod_id or entry.key or "mod"
    number = version.version_number or version.name or version.version_id or "unknown"
    return safe_filename(base + "-" + number + JAR_SUFFIX, fallback="download" + JAR_SUFFIX)


def safe_filename(name: str, *, fallback: str) -> str:
    """把下载文件名变成本机安全的文件名（PRD §14.2 / §14.5 第 4 条）。

    规则：空名用 fallback；Windows 非法字符与控制字符替换成 _；
    去掉首尾空格与结尾的点；长度截断到 200 字符且保留 .jar 后缀。
    """
    text = (name or "").strip() or (fallback or "").strip()
    if not text:
        text = "download" + JAR_SUFFIX
    cleaned = "".join(REPLACEMENT if (ch in ILLEGAL_CHARS or ch < " ") else ch for ch in text)
    cleaned = cleaned.strip().rstrip(".")
    if not cleaned:
        cleaned = "download" + JAR_SUFFIX
    if len(cleaned) <= MAX_FILENAME:
        return cleaned
    if cleaned.lower().endswith(JAR_SUFFIX):
        keep = MAX_FILENAME - len(JAR_SUFFIX)
        return cleaned[:keep] + JAR_SUFFIX
    return cleaned[:MAX_FILENAME]


def plan_for(report: Report, target_dir: Path) -> DownloadPlan:
    """按报告生成下载计划（PRD §14.2）。

    参数：
        report: 一次检查的报告。
        target_dir: 下载目标目录（这里只用来拼路径，不创建、不写盘）。
    返回：
        DownloadPlan；不能下的条目连同原因进 skipped。
    """
    root = Path(target_dir)
    items: list[DownloadItem] = []
    skipped: list[tuple[ModEntry, str]] = []
    for report_item in report.iter_items():
        entry = report_item.mod
        if report_item.status not in DOWNLOADABLE:
            skipped.append((entry, "download.skip.status." + report_item.status.value))
            continue
        version = pick_version(report_item)
        if version is None:
            skipped.append((entry, SKIP_NO_VERSION))
            continue
        file = pick_file(version)
        if file is None:
            skipped.append((entry, SKIP_NO_JAR))
            continue
        target = root / safe_filename(file.filename,
                                      fallback=fallback_filename(entry, version))
        items.append(DownloadItem(entry=entry, version=version, file=file, target=target))
    return DownloadPlan(items=tuple(items), skipped=tuple(skipped))


def conflicts(plan: DownloadPlan) -> tuple[DownloadItem, ...]:
    """目标目录里已经存在同名文件的条目（只判断，不写盘、不询问）。"""
    return tuple(item for item in plan.items if Path(item.target).exists())


def extra_files_count(plan: DownloadPlan) -> int:
    """有几个模组除主文件外还有附加文件（PRD §14.4 的 ℹ 那一行）。"""
    return sum(1 for item in plan.items if len(item.version.files) > 1)


def overwrite_key(item: DownloadItem) -> str:
    """overwrite 映射的键：目标文件名（CLI 与 download_all 必须用同一个）。"""
    return Path(item.target).name

#: 429 最多连续放行几次（限流由 fetcher 自己 pause，这里只防死循环）
MAX_RATE_RETRIES: Final[int] = 5
#: 失败重试的退避秒数：第 1 次失败等 1 秒，第 2 次等 2 秒（PRD §14.5 第 7 条）
BACKOFF_SECONDS: Final[tuple[float, ...]] = (1.0, 2.0)
#: 用户选择跳过
SKIP_USER: Final[str] = "download.skip.user"
#: 计划期就注定下不了的两种条目（PRD §14.5 第 2 / 17 条：要在汇总里写明原因）
SKIP_NO_JAR: Final[str] = "download.skip.no_jar"
SKIP_NO_VERSION: Final[str] = "download.skip.no_version"


def _error_key(exc: BaseException) -> str:
    """把 fetcher 抛出的异常映射成失败原因文案 key。"""
    if isinstance(exc, ProviderVerifyError):
        return "download.error.verify"
    if isinstance(exc, OSError):
        return "download.error.write"
    if isinstance(exc, ProviderError):
        return "download.error.net"
    return "download.error.net"


def _error_detail(exc: BaseException) -> str:
    """失败原因里的 {detail}（领域异常自带中文说明，其它用类名）。"""
    if isinstance(exc, ModcheckError):
        return exc.message
    return type(exc).__name__ + ": " + str(exc)


def cleanup_parts(items: Sequence[DownloadItem]) -> int:
    """删除这些条目残留的 .part 临时文件（返回删掉几个）。

    取消下载时必须调用：PRD §14.5 第 5 条要求"没下完的临时文件已清理"。
    """
    removed = 0
    for item in items:
        temp = part_path(item.target)
        try:
            if temp.exists():
                temp.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def download_all(plan: DownloadPlan, fetcher, *,
                 overwrite: Mapping[str, bool] | None = None,
                 on_progress: Callable[[DownloadItem, int, int], None] | None = None,
                 cancel: threading.Event | None = None,
                 retries: int = 2, jobs: int = 3,
                 sleep: Callable[[float], None] | None = None) -> DownloadReport:
    """并发下载计划里的全部文件（PRD §14.2 / §14.5，R3-B03）。

    参数：
        plan: plan_for 生成的计划。
        fetcher: 实现 download(url, dest, *, sha1, on_chunk, timeout) -> int 的对象
            （由 CLI 注入 providers/http.py 的 HttpClient；测试注入假 fetcher）。
        overwrite: 目标文件名 -> 是否覆盖；False 表示用户选择跳过（默认全部覆盖）。
        on_progress: 进度回调（调用方负责节流）。
        cancel: 取消事件；置位后停止派发新任务，删掉残留 .part，已下好的文件保留。
        retries: 每个文件最多重试几次（默认 2，退避 1s / 2s）；429 不计入。
        jobs: 同时下载几个文件（默认 3，与限速器无关）。
        sleep: 注入的睡眠函数（测试用；默认 time.sleep）。

    返回：
        DownloadReport；ok + skipped + failed + cancelled == len(items)。
    """
    started = time.monotonic()
    do_sleep = sleep if sleep is not None else time.sleep
    workers = max(1, int(jobs))
    max_tries = max(0, int(retries)) + 1
    plan_items = list(plan.items)
    results: dict[int, DownloadItem] = {}
    queue: list[tuple[int, DownloadItem]] = []
    for index, item in enumerate(plan_items):
        if overwrite is not None and overwrite.get(overwrite_key(item)) is False:
            results[index] = replace(item, status=STATUS_SKIPPED, message_key=SKIP_USER)
            continue
        queue.append((index, item))

    def work(index: int, item: DownloadItem) -> DownloadItem:
        """下载一个文件（含重试）；任何异常都转成失败条目，绝不冒泡。"""
        attempts = 0
        rate_limits = 0
        seen = 0
        while True:
            if cancel is not None and cancel.is_set():
                return replace(item, status=STATUS_CANCELLED, bytes_done=seen)
            try:
                written = fetcher.download(item.file.url, item.target,
                                           sha1=item.file.hashes.get("sha1"),
                                           on_chunk=make_chunk(item))
                return replace(item, status=STATUS_OK, bytes_done=written)
            except ProviderRateLimited as exc:
                # 限流不是这个文件的问题：不计入重试次数（PRD §14.3）
                rate_limits += 1
                if rate_limits > MAX_RATE_RETRIES:
                    return replace(item, status=STATUS_FAILED, bytes_done=seen,
                                   message_key="download.error.net",
                                   detail=_error_detail(exc))
                continue
            except Exception as exc:            # noqa: BLE001 - 单文件失败不能影响其它文件
                attempts += 1
                if attempts >= max_tries:
                    status = (STATUS_VERIFY_FAILED
                              if isinstance(exc, ProviderVerifyError) else STATUS_FAILED)
                    # 兜底：fetcher 没清干净的 .part 由这里删掉，绝不留半成品
                    cleanup_parts([item])
                    return replace(item, status=status, bytes_done=seen,
                                   message_key=_error_key(exc), detail=_error_detail(exc))
                do_sleep(BACKOFF_SECONDS[min(attempts - 1, len(BACKOFF_SECONDS) - 1)])

    def make_chunk(item: DownloadItem) -> Callable[[int], None]:
        """把 on_chunk 折成 on_progress 回调（含已下载字节数）。"""
        state = {"done": 0}

        def on_chunk(size: int) -> None:
            state["done"] += int(size)
            if on_progress is not None:
                on_progress(item, state["done"], int(item.file.size or 0))

        return on_chunk

    cancelled = False
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures: dict[object, tuple[int, DownloadItem]] = {}
        cursor = 0
        while cursor < len(queue) or futures:
            while not cancelled and cursor < len(queue) and len(futures) < workers:
                if cancel is not None and cancel.is_set():
                    cancelled = True
                    break
                index, item = queue[cursor]
                futures[pool.submit(work, index, item)] = (index, item)
                cursor += 1
            if not futures:
                break
            done_futures, _ = wait(list(futures), return_when=FIRST_COMPLETED)
            for future in done_futures:
                index, item = futures.pop(future)
                try:
                    results[index] = future.result()
                except Exception as exc:        # noqa: BLE001 - 兜底，绝不让线程异常逃逸
                    results[index] = replace(item, status=STATUS_FAILED,
                                             message_key=_error_key(exc))
            if cancel is not None and cancel.is_set():
                cancelled = True

    if cancelled:
        remaining = [item for index, item in queue if index not in results]
        cleanup_parts(remaining)
        for index, item in queue:
            results.setdefault(index, replace(item, status=STATUS_CANCELLED))
    final = tuple(results.get(index, item) for index, item in enumerate(plan_items))
    ok = sum(1 for item in final if item.status == STATUS_OK)
    skipped = sum(1 for item in final if item.status == STATUS_SKIPPED)
    failed = sum(1 for item in final if item.status in (STATUS_FAILED, STATUS_VERIFY_FAILED))
    bytes_total = sum(item.bytes_done for item in final if item.status == STATUS_OK)
    return DownloadReport(items=final, ok=ok, skipped=skipped, failed=failed,
                          bytes_total=bytes_total, elapsed=time.monotonic() - started,
                          cancelled=cancelled)
