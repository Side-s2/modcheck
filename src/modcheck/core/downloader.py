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

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from modcheck.core.models import FileInfo, ModEntry, Status, VersionInfo
from modcheck.core.report import Report, ReportItem

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
    """是否算「可下载的模组文件」。

    filename 为空的 primary 也算：PRD §14.5 第 3 条要求这种文件用
    {slug}-{version_number}.jar 兜底，而不是把它当成"没有 jar"跳过。
    """
    name = (item.filename or "").strip().lower()
    if name.endswith(JAR_SUFFIX):
        return True
    return not name and bool(item.primary)


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
            skipped.append((entry, "download.skip.no_version"))
            continue
        file = pick_file(version)
        if file is None:
            skipped.append((entry, "download.skip.no_jar"))
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
