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
    ⑦ （调用方）与已有清单合并 -> 原子写盘

--from-list 模式（决策 D20）：没有 jar，跳过 ①②③，全部标 GUESS，且不发起指纹请求。

落盘不在本模块：scan_dirs / scan_from_list 只负责"识别出条目"，
写哪份清单由调用方决定（CLI 是 run_scan），所以这里没有 profiles_dir 参数。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterable, Sequence

from modcheck.core.filename import is_archive_like, is_disabled_like, parse_jar_filename
from modcheck.core.hashid import sha1_of_file
from modcheck.core.jarmeta import read_jar_meta
from modcheck.core.matching import candidate_names, match_exact
from modcheck.core.models import Detected, MatchStatus, ModEntry, ProjectHit, SourceKind
from modcheck.errors import ConfigError, ProviderError
from modcheck.i18n import t
from modcheck.storage.profiles import key_of, merge_entries

if TYPE_CHECKING:  # 只为类型注解；运行时不引入具体数据源（依赖注入）
    from modcheck.providers.base import BaseProvider

#: 默认清单名
DEFAULT_PROFILE = "demo"
#: 单批指纹反查的哈希上限
HASH_BATCH = 100

#: 进度回调：(已完成, 总数, 当前文件名)
ProgressFn = Callable[[int, int, str], None]
#: 取消探针：返回 True 表示调用方要求停下
StopFn = Callable[[], bool]


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
              should_stop: StopFn | None = None) -> ScanReport:
    """扫描若干目录（默认不递归），返回识别结果。

    参数：
        directories: 要扫描的目录（每个都必须存在，否则抛 ConfigError）。
        provider: 注入的数据源；None 表示一个可用的都没有（只靠 jar 内信息识别）。
        on_progress: 每读一个 jar 回调一次 (已完成, 总数, 文件名)。GUI/CLI 各自决定怎么画。
        should_stop: 返回 True 时**立刻停下**（在下一个 jar 之前），结果里 cancelled=True。

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
    metas = {}
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
                digest = sha1_of_file(jar)
            except OSError:
                continue
            digests[jar] = digest
            metas[jar] = read_jar_meta(jar)

    hash_hits = _lookup_hashes(digests, provider, report)

    for directory, jars, skipped, subdirs in per_dir:
        if should_stop is not None and should_stop():
            report.cancelled = True
            return report
        report.skipped.extend(skipped)
        report.subdirs.extend(subdirs)
        for jar in jars:
            meta = metas[jar]
            digest = digests.get(jar, "")
            hit = hash_hits.get(digest)
            if meta.error_code == "broken":
                report.skipped.append(SkipItem(jar.name, t("scan.skipped.broken")))
                continue
            if hit is not None:
                entry = _entry_from_hash(jar, meta, digest, hit)
                report.by_hash += 1
                report.entries.append(entry)
                candidates.append((jar, entry))
                continue
            if not meta.has_meta:
                # 裁决 D35：**必须进清单**。
                # 漏掉一个模组比多列一个危险得多 —— 漏掉的往往正是让服务器起不来的那个；
                # 清单与 mods 文件夹不一致还会让用户彻底不再信任这份清单。
                # 这里标成"未识别"，检查时显示 ⚪ 未判定 + 建议。
                entry = _entry_from_filename(jar, digest)
                report.unidentified.append(jar.name)
                report.entries.append(entry)
                candidates.append((jar, entry))
                continue
            entry = _entry_from_meta(jar, meta, digest)
            report.by_meta += 1
            report.entries.append(entry)
            candidates.append((jar, entry))

    _resolve_slugs(report.entries, provider)
    _resolve_by_name(candidates, provider, report, should_stop=should_stop)
    if report.cancelled:                      # 搜索阶段被叫停：不再做合并（结果要丢就给个干净信号）
        return report
    _merge_duplicates(report)
    return report


def _resolve_slugs(entries: list[ModEntry], provider: "BaseProvider | None") -> None:
    """把"项目 ID"换成人类可读的 slug（裁决 D38）。

    两条识别路径原本写进去的是不同种类的标识：hash 反查给的是 project_id，
    搜索命中给的是 slug。Modrinth 两种都接受，所以查询不会出错，但：
      ① 清单是给用户手改的，看到 fQEb0iXm 根本不知道那是什么；
      ② 两条路径的 key 不一致，换文件名重扫时兜底失效会出现重复条目。
    这里统一成 slug —— 只在首次扫描、且条目还没解析过 slug 时发生。
    """
    if provider is None:
        return
    pending = {entry.sources.get("modrinth") for entry in entries if entry.sources.get("modrinth")}
    if not pending:
        return
    resolved: dict[str, str] = {}
    for entry in entries:
        ident = entry.sources.get("modrinth")
        if not ident:
            continue
        if ident not in resolved:
            try:
                info = provider.get_project(ident)
            except ProviderError:
                resolved[ident] = ident
                continue
            resolved[ident] = info.slug if (info is not None and info.slug) else ident
        if resolved[ident] != ident:
            entry.sources["modrinth"] = resolved[ident]
            entry.key = key_of(entry)


def _lookup_hashes(digests: dict[Path, str], provider: "BaseProvider | None",
                   report: ScanReport) -> dict[str, object]:
    """批量指纹反查；失败只记一行提示，不中断扫描。"""
    if not digests:
        return {}
    if provider is None:
        report.offline = True
        report.warnings.append(t("scan.offline"))
        return {}
    unique = sorted({digest for digest in digests.values() if digest})
    hits: dict[str, object] = {}
    for start in range(0, len(unique), HASH_BATCH):
        batch = unique[start:start + HASH_BATCH]
        try:
            found = provider.resolve_by_hash(batch)
        except ProviderError:
            report.offline = True
            report.warnings.append(t("scan.offline"))
            return hits
        hits.update(found)
    return hits


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
                              mod_version=parsed.mod_version)
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
                              mod_version=meta.version or parsed.mod_version)
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


def _resolve_by_name(candidates: list[tuple[Path, ModEntry]], provider: "BaseProvider | None",
                     report: ScanReport, *, should_stop: StopFn | None = None) -> None:
    """对还没有平台项目的条目做精确同名搜索（失败只降级，不中断）。"""
    if not candidates:
        return
    if provider is None:
        report.offline = True
        return
    cache: dict[str, list[ProjectHit]] = {}
    for jar, entry in candidates:
        # 搜索是逐个出网的，取消在这里也必须能生效
        if should_stop is not None and should_stop():
            report.cancelled = True
            return
        if entry.sources.get("modrinth"):
            continue
        matched = False
        for name in candidate_names(entry):
            if name not in cache:
                try:
                    cache[name] = provider.search(name, limit=10)
                except ProviderError:
                    report.offline = True
                    cache[name] = []
            result = match_exact(cache[name], [name])
            if result.hit is not None:
                entry.sources["modrinth"] = result.hit.slug
                entry.display_name = entry.display_name or result.hit.title
                entry.match_status = MatchStatus.EXACT
                entry.source_kind = SourceKind.SEARCH
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
                   should_stop: StopFn | None = None) -> ScanReport:
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

    _resolve_by_name([(Path(e.file_name or "x.jar"), e) for e in report.entries], provider,
                     report, should_stop=should_stop)
    if report.cancelled:
        return report
    _merge_duplicates(report)
    return report


__all__ = ["DEFAULT_PROFILE", "HASH_BATCH", "ProgressFn", "StopFn", "SkipItem", "ScanReport",
           "scan_dirs", "scan_from_list"]
