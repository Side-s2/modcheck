"""scan 流程：扫描 mods 文件夹 / 文件名清单 -> 结构化识别结果。

本模块是「流程」层：**不打印任何东西**，进度用回调、取消用探针，
结果全部装在 ScanReport 里返回。CLI 与未来的 GUI 共用这一份流水线。

流水线（每一步失败都不许影响主流程）：
    ① 列目录（默认不递归）：jar / 已禁用 / 其它
    ② 逐个读 jar 元数据 + 流式 sha1
    ③ 批量 POST /version_files 反查指纹（每批 <= 100）
    ④ 未命中的用候选名做精确同名搜索
    ⑤ 仍不行 -> 文件名兜底（低置信，标 GUESS）
    ⑥ 同 modid / 同 sha1 合并 + 显式告警
    ⑦ save_scan_result()：与已有清单合并 -> 原子写盘

--from-list 模式（决策 D20）：没有 jar，跳过 ①②③，全部标 GUESS，且不发起指纹请求。

**识别与落盘分开**：scan_dirs / scan_from_list 只负责"识别出条目"（不碰清单文件），
写哪份清单由 save_scan_result 决定 —— 半份结果（cancelled）绝不允许落盘。
这样 GUI 三期可以直接复用同一条流水线，不必自己重写"合并 + 原子写"。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterable, Iterator, Sequence

from modcheck.core.filename import is_archive_like, is_disabled_like, parse_jar_filename
from modcheck.core.hashid import sha1_of_file
from modcheck.core.jarmeta import JarMeta, read_jar_meta
from modcheck.core.matching import candidate_names, match_exact
from modcheck.core.models import Detected, MatchStatus, ModEntry, ProjectHit, SourceKind
from modcheck.errors import (ConfigError, ProviderError, ProviderNetworkError, ProviderRateLimited,
                             UserCancelled)
from modcheck.i18n import t
from modcheck.providers.network import network_budget, remaining_time
from modcheck.storage.profiles import (MergeStats, key_of, load_profile, merge_entries,
                                       new_profile, profile_path, save_profile)

if TYPE_CHECKING:  # 只为类型注解；运行时不引入具体数据源（依赖注入）
    from modcheck.providers.base import BaseProvider

#: 默认清单名
DEFAULT_PROFILE = "demo"
#: 单批指纹反查的哈希上限
HASH_BATCH = 100
NETWORK_TIMEOUT = 120.0

#: 进度回调：(已完成, 总数, 当前文件名)
ProgressFn = Callable[[int, int, str], None]
#: 取消探针：返回 True 表示调用方要求停下
StopFn = Callable[[], bool]
#: 落盘提示回调：(文案 key, **格式化参数)。流程层不打印，只把"该说一句什么"交出去；
#: 为什么需要它：那句"没有名为 X 的清单，将新建一个"必须出现在**写盘之前**的位置
#: （CLI 的逐字输出如此），只有回调能在不打印的前提下保住顺序。
NoticeFn = Callable[..., None]


@dataclass(slots=True)
class SkipItem:
    """被跳过的文件与原因。"""

    name: str
    reason: str


@dataclass(slots=True)
class ScanReport:
    """一次扫描的结果（纯数据，便于单测）。"""

    entries: list[ModEntry] = field(default_factory=list)
    skipped: list[SkipItem] = field(default_factory=list)
    subdirs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    files_seen: int = 0
    by_hash: int = 0
    by_meta: int = 0
    by_search: int = 0
    guessed: int = 0
    offline: bool = False
    #: 没有可读元数据的 jar（已列入清单，但需要人工确认）
    unidentified: list[str] = field(default_factory=list)
    #: 被 should_stop 中途叫停：条目是**半份**的，调用方绝不许把它落盘。
    #: （每条 entry 本身都是构造完整的，不存在"写坏了的条目"。）
    cancelled: bool = False


# ---------------------------------------------------------------- 目录模式
def scan_dirs(directories: Sequence[Path], *, provider: "BaseProvider | None",
              on_progress: ProgressFn | None = None,
              should_stop: StopFn | None = None,
              on_network_progress: ProgressFn | None = None,
              network_timeout: float = NETWORK_TIMEOUT) -> ScanReport:
    """扫描若干目录（默认不递归），返回识别结果。

    参数：
        directories: 要扫描的目录（每个都必须存在，否则抛 ConfigError）。
        provider: 注入的数据源；None 表示一个可用的都没有（只靠 jar 内信息识别）。
        on_progress: 读取每个 jar 前回调 (序号, 总数, 文件名)。
        should_stop: 请求取消时返回 True。
        on_network_progress: 联网操作前回调 (序号, 阶段总数, 操作说明)。
        network_timeout: 整个联网识别阶段的秒数上限。

    抛出：
        ConfigError: 目录不存在。
    """
    report = ScanReport()
    candidates: list[tuple[Path, ModEntry]] = []
    per_dir: list[tuple[Path, list[Path], list[SkipItem], list[str]]] = []

    for raw in directories:
        if should_stop is not None and should_stop():
            report.cancelled = True
            return report
        directory = Path(raw)
        if not directory.is_dir():
            raise ConfigError(t("err.dir.not_found", path=directory))
        jars: list[Path] = []
        skipped: list[SkipItem] = []
        subdirs: list[str] = []
        for item in sorted(directory.iterdir(), key=lambda p: p.name):
            if item.is_dir():
                subdirs.append(item.name)
                continue
            report.files_seen += 1
            name = item.name
            if is_disabled_like(name):
                skipped.append(SkipItem(name, t("scan.skipped.disabled")))
                continue
            if not is_archive_like(name):
                skipped.append(SkipItem(name, t("scan.skipped.not_jar")))
                continue
            jars.append(item)
        per_dir.append((directory, jars, skipped, subdirs))

    digests: dict[Path, str] = {}
    metas: dict[Path, JarMeta] = {}
    # 用户反馈：30 个模组扫描也要等不少时间，设计容量还更大 —— 必须有进度。
    # 读 jar + 算 sha1 是这里最慢的一步，进度就报在这一段（由调用方决定画成什么）。
    total_jars = sum(len(jars) for _d, jars, _s, _sub in per_dir)
    done = 0
    for _directory, jars, _skipped, _subdirs in per_dir:
        for jar in jars:
            # 中途取消必须真的生效：这里是最耗时的一段，回车/Ctrl+C 后不能再读完整个文件夹
            if should_stop is not None and should_stop():
                report.cancelled = True
                return report
            done += 1
            if on_progress is not None:
                on_progress(done, total_jars, jar.name)
            try:
                digest = sha1_of_file(jar, should_stop=should_stop)
            except UserCancelled:
                report.cancelled = True
                return report
            except OSError:
                report.skipped.append(SkipItem(jar.name, t("scan.skipped.unreadable")))
                continue
            digests[jar] = digest
            metas[jar] = read_jar_meta(jar)

    # 先准备所有本地条目，联网失败时也能保留完整的扫描范围。
    for _directory, jars, skipped, subdirs in per_dir:
        if should_stop is not None and should_stop():
            report.cancelled = True
            return report
        report.skipped.extend(skipped)
        report.subdirs.extend(subdirs)
        for jar in jars:
            meta = metas.get(jar)
            if meta is None:
                continue
            digest = digests[jar]
            if meta.error_code == "broken":
                report.skipped.append(SkipItem(jar.name, t("scan.skipped.broken")))
                continue
            if not meta.has_meta:
                # 裁决 D35：**必须进清单**。
                # 漏掉一个模组比多列一个危险得多 —— 漏掉的往往正是让服务器起不来的那个；
                # 清单与 mods 文件夹不一致还会让用户彻底不再信任这份清单。
                # 这里标成"未识别"，检查时显示 ⚪ 未判定 + 建议。
                entry = _entry_from_filename(jar, digest)
            else:
                entry = _entry_from_meta(jar, meta, digest)
            candidates.append((jar, entry))

    if not _identify_online(candidates, report, provider, should_stop, on_network_progress,
                            network_timeout, metas=metas):
        return report
    if should_stop is not None and should_stop():
        report.cancelled = True
        return report
    for jar, entry in candidates:
        if entry.source_kind is SourceKind.HASH:
            report.by_hash += 1
        elif metas[jar].has_meta:
            report.by_meta += 1
        else:
            report.unidentified.append(jar.name)
        report.entries.append(entry)
    _merge_duplicates(report)
    return report


# ---------------------------------------------------------------- 落盘
@dataclass(frozen=True, slots=True)
class SaveOutcome:
    """一次扫描结果的落盘结果。"""

    path: Path
    #: 合并后的条目（已有 + 本次扫描）
    merged: list[ModEntry]
    #: 合并统计（新增 / 合并 / 重复文件名告警）
    stats: MergeStats
    #: 清单文件此前不存在（调用方据此说一句"将新建一个"）
    created: bool
    #: 是否整份替换（--new）
    replaced: bool


def save_scan_result(report: ScanReport, *, profiles_dir: Path, profile_name: str,
                     new: bool = False, on_notice: NoticeFn | None = None,
                     refresh_files: bool = True) -> SaveOutcome:
    """把扫描结果与已有清单合并后原子写盘（流水线第 ⑦ 步）。

    参数：
        report: scan_dirs / scan_from_list 的结果。
        profiles_dir: 清单目录（CLI 传 ctx.profiles_dir）。
        profile_name: 要写入的清单名。
        new: True 表示忽略已有清单，整份替换（--new）。
        on_notice: 落盘过程中的提示回调 (key, **kw)；**只在这一个地方会被调用**：
            清单文件此前不存在时（对应的正是 CLI 那句"没有名为 X 的清单，将新建一个"）。
            它必须在写盘**之前**触发，否则 CLI 的逐字输出顺序会变。

    返回：
        SaveOutcome（路径、合并后的条目、统计、是否新建、是否整份替换）。

    抛出：
        UserCancelled: report.cancelled 为真 —— 半份结果绝不落盘。
        ProfileError: 读不了已有清单或写不进去（内存与磁盘都不变）。
        ConfigError: 清单名不合法。
    """
    if report.cancelled:
        # 取消时写盘 = 用户的清单会被悄悄改窄，这是最不能接受的一种"省事"
        raise UserCancelled(t("scan.cancelled"))
    path = profile_path(Path(profiles_dir), profile_name)
    created = not path.exists()
    if created and on_notice is not None:
        on_notice("scan.profile_not_exist", name=profile_name)
    profile = None
    existing: list[ModEntry] = []
    if not new and not created:
        profile = load_profile(path)
        existing = profile.mods
    merged, stats = merge_entries(existing, report.entries, refresh_files=refresh_files)
    if profile is None:
        profile = new_profile(profile_name)
    profile.mods = merged
    save_profile(profile, path)
    return SaveOutcome(path=path, merged=merged, stats=stats, created=created, replaced=bool(new))


def _identify_online(candidates: list[tuple[Path, ModEntry]], report: ScanReport,
                     provider: "BaseProvider | None", should_stop: StopFn | None,
                     on_progress: ProgressFn | None, timeout: float, *,
                     metas: dict[Path, JarMeta] | None = None) -> bool:
    if not candidates:
        return True
    if provider is None:
        report.offline = True
        report.warnings.append(t("scan.offline"))
        return True
    try:
        with network_budget(timeout, should_stop):
            if metas is not None:
                try:
                    _identify_hashes(candidates, metas, provider, on_progress)
                    _resolve_slugs(candidates, provider, on_progress)
                except (ProviderNetworkError, ProviderRateLimited):
                    raise
                except ProviderError as exc:
                    _note_network_error(report, exc)
            _resolve_by_name(candidates, provider, report, on_progress)
            remaining_time()
    except UserCancelled:
        report.cancelled = True
        return False
    except ProviderError as exc:
        _note_network_error(report, exc)
    return True


def _note_network_error(report: ScanReport, exc: ProviderError) -> None:
    report.offline = True
    warning = t("scan.network_incomplete", detail=exc.message)
    if warning not in report.warnings:
        report.warnings.append(warning)


def _identify_hashes(candidates: list[tuple[Path, ModEntry]], metas: dict[Path, JarMeta],
                     provider: "BaseProvider", on_progress: ProgressFn | None) -> None:
    by_digest: dict[str, list[int]] = {}
    for index, (_jar, entry) in enumerate(candidates):
        if entry.sha1:
            by_digest.setdefault(entry.sha1, []).append(index)
    for batch in _batches(sorted(by_digest), "正在查询文件指纹", on_progress):
        for digest, hit in provider.resolve_by_hash(batch).items():
            for index in by_digest.get(digest, ()):
                jar, _entry = candidates[index]
                candidates[index] = (jar, _entry_from_hash(jar, metas[jar], digest, hit))


def _resolve_slugs(candidates: list[tuple[Path, ModEntry]], provider: "BaseProvider",
                   on_progress: ProgressFn | None) -> None:
    by_id: dict[str, list[ModEntry]] = {}
    for _jar, entry in candidates:
        if ident := entry.sources.get("modrinth"):
            by_id.setdefault(ident, []).append(entry)
    for batch in _batches(sorted(by_id), "正在获取项目名称", on_progress):
        for ident, info in provider.get_projects(batch).items():
            if info.slug:
                for entry in by_id.get(ident, ()):
                    entry.sources["modrinth"] = info.slug
                    entry.key = key_of(entry)


def _batches(values: list[str], phase: str, on_progress: ProgressFn | None) -> Iterator[list[str]]:
    total = (len(values) + HASH_BATCH - 1) // HASH_BATCH
    for index, start in enumerate(range(0, len(values), HASH_BATCH), start=1):
        remaining_time()
        if on_progress is not None:
            on_progress(index, total, phase)
        yield values[start:start + HASH_BATCH]


def _entry_from_hash(jar: Path, meta, digest: str, version) -> ModEntry:
    """指纹命中：高置信，同时拿到"用户当前装的确切版本"。"""
    parsed = parse_jar_filename(jar.name)
    name = meta.name or parsed.name or str(getattr(version, "project_id", "") or jar.stem)
    entry = ModEntry(
        key="", display_name=name, cn_name=parsed.cn_name, mod_id=meta.mod_id,
        file_name=jar.name, sha1=digest,
        sources={"modrinth": str(getattr(version, "project_id", "") or "") or None,
                 "curseforge": None},
        match_status=MatchStatus.EXACT, source_kind=SourceKind.HASH,
        current_version=str(getattr(version, "version_number", "") or "") or None,
        notes=parsed.notes if hasattr(parsed, "notes") else "",
    )
    entry.detected = Detected(mc_versions=list(parsed.mc_version and [parsed.mc_version] or []),
                              loaders=[parsed.loader] if parsed.loader else [],
                              mod_version=meta.version or parsed.mod_version,
                              mod_ids=list(meta.mod_ids))
    if meta.mc_hint and meta.mc_hint not in entry.detected.mc_versions:
        entry.detected.mc_versions.insert(0, meta.mc_hint)
    if meta.loader_hint and meta.loader_hint not in entry.detected.loaders:
        entry.detected.loaders.insert(0, meta.loader_hint)
    entry.key = key_of(entry)
    return entry


def _entry_from_meta(jar: Path, meta, digest: str) -> ModEntry:
    """只有 jar 元数据：高置信，但还没有平台项目。"""
    parsed = parse_jar_filename(jar.name)
    entry = ModEntry(
        key="", display_name=meta.name or parsed.name or jar.stem, cn_name=parsed.cn_name,
        mod_id=meta.mod_id, file_name=jar.name, sha1=digest,
        sources={"modrinth": None, "curseforge": None},
        match_status=MatchStatus.UNMATCHED, source_kind=SourceKind.JAR_META,
        current_version=meta.version,
    )
    mc_versions = []
    if meta.mc_hint:
        mc_versions.append(meta.mc_hint)
    if parsed.mc_version and parsed.mc_version not in mc_versions:
        mc_versions.append(parsed.mc_version)
    loaders = [meta.loader_hint] if meta.loader_hint else []
    if parsed.loader and parsed.loader not in loaders:
        loaders.append(parsed.loader)
    entry.detected = Detected(mc_versions=mc_versions, loaders=loaders,
                              mod_version=meta.version or parsed.mod_version,
                              mod_ids=list(meta.mod_ids))
    entry.key = key_of(entry)
    return entry


def _entry_from_filename(jar: Path, digest: str) -> ModEntry:
    """没有元数据时的兜底条目：靠文件名尽力识别（低置信，但**绝不丢弃**）。"""
    parsed = parse_jar_filename(jar.name)
    entry = ModEntry(
        key="", display_name=parsed.name or parsed.cn_name or jar.stem,
        cn_name=parsed.cn_name, mod_id=None, file_name=jar.name, sha1=digest,
        sources={"modrinth": None, "curseforge": None},
        match_status=MatchStatus.UNMATCHED, source_kind=SourceKind.FILENAME,
    )
    entry.detected = Detected(
        mc_versions=[parsed.mc_version] if parsed.mc_version else [],
        loaders=[parsed.loader] if parsed.loader else [],
        mod_version=parsed.mod_version)
    entry.key = key_of(entry)
    return entry


def _resolve_by_name(candidates: list[tuple[Path, ModEntry]], provider: "BaseProvider",
                     report: ScanReport, on_progress: ProgressFn | None) -> None:
    """对还没有平台项目的条目做精确同名搜索。"""
    pending = [(jar, entry) for jar, entry in candidates if not entry.sources.get("modrinth")]
    cache: dict[str, list[ProjectHit]] = {}
    for index, (jar, entry) in enumerate(pending, start=1):
        remaining_time()
        if on_progress is not None:
            on_progress(index, len(pending), f"正在搜索 {entry.best_name}")
        matched = False
        for name in candidate_names(entry):
            remaining_time()
            if name not in cache:
                try:
                    cache[name] = provider.search(name, limit=10)
                except (ProviderNetworkError, ProviderRateLimited):
                    raise
                except ProviderError as exc:
                    cache[name] = []
                    if not report.warnings:
                        _note_network_error(report, exc)
            result = match_exact(cache[name], [name])
            if result.hit is not None:
                entry.sources["modrinth"] = result.hit.slug
                entry.display_name = entry.display_name or result.hit.title
                entry.match_status = MatchStatus.EXACT
                entry.source_kind = SourceKind.SEARCH
                entry.key = key_of(entry)
                report.by_search += 1
                matched = True
                break
        if not matched:
            # 兜底：文件名猜测（低置信；报告里会带 ~ 标记）
            parsed = parse_jar_filename(jar.name)
            if parsed.name_candidates and not entry.mod_id:
                entry.match_status = MatchStatus.GUESS
                entry.source_kind = SourceKind.FILENAME
                report.guessed += 1
            entry.key = key_of(entry)


def _merge_duplicates(report: ScanReport) -> None:
    """同一 modid / 同一 sha1 的多个文件合并，并产生告警。"""
    merged, stats = merge_entries([], report.entries)
    report.entries = merged
    report.warnings.extend(stats.warnings)


# ---------------------------------------------------------------- 仅文件名模式
def scan_from_list(path: Path, *, provider: "BaseProvider | None",
                   known_mc_versions: Iterable[str] | None = None,
                   on_progress: ProgressFn | None = None,
                   should_stop: StopFn | None = None,
                   on_network_progress: ProgressFn | None = None,
                   network_timeout: float = NETWORK_TIMEOUT) -> ScanReport:
    """从"每行一个文件名"的文本清单导入（决策 D20：全部低置信，不发指纹请求）。

    抛出：
        ConfigError: 文件读不到，或里面一行有效内容都没有。
    """
    target = Path(path)
    report = ScanReport()
    try:
        # utf-8-sig：Windows 记事本/PowerShell 写的 UTF-8 清单**带 BOM**，
        # 用 utf-8 读会把 U+FEFF 粘在第一条记录上，导致它永远匹配不上。
        text = target.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(t("err.from_list.missing", path=target)) from exc
    lines = [line.lstrip("\ufeff").strip() for line in text.splitlines()]
    lines = [line for line in lines if line and not line.startswith("#")]
    report.files_seen = len(lines)
    if not lines:
        raise ConfigError(t("err.from_list.missing", path=target))

    total = len(lines)
    for index, line in enumerate(lines, start=1):
        if should_stop is not None and should_stop():
            report.cancelled = True
            return report
        if on_progress is not None:
            on_progress(index, total, line)
        parsed = parse_jar_filename(line, known_mc_versions=known_mc_versions)
        name = parsed.name or parsed.cn_name or line
        entry = ModEntry(
            key="", display_name=name, cn_name=parsed.cn_name, mod_id=None,
            file_name=line, sha1=None,
            sources={"modrinth": None, "curseforge": None},
            match_status=MatchStatus.GUESS, source_kind=SourceKind.FILENAME,
            current_version=None,
        )
        entry.detected = Detected(
            mc_versions=[parsed.mc_version] if parsed.mc_version else [],
            loaders=[parsed.loader] if parsed.loader else [],
            mod_version=parsed.mod_version)
        entry.key = key_of(entry)
        report.entries.append(entry)
        if parsed.name:
            report.guessed += 1

    candidates = [(Path(e.file_name or "x.jar"), e) for e in report.entries]
    if not _identify_online(candidates, report, provider, should_stop, on_network_progress,
                            network_timeout):
        return report
    _merge_duplicates(report)
    return report


__all__ = ["DEFAULT_PROFILE", "HASH_BATCH", "NoticeFn", "ProgressFn", "SaveOutcome",
           "SkipItem", "ScanReport", "StopFn", "save_scan_result", "scan_dirs", "scan_from_list"]
