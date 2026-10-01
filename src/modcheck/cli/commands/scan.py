"""scan 命令：扫描 mods 文件夹建立/合并模组清单（T-20 识别流水线）。

流水线（每一步失败都不许影响主流程）：
    ① 列目录（默认不递归）：jar / 已禁用 / 其它
    ② 逐个读 jar 元数据 + 流式 sha1
    ③ 批量 POST /version_files 反查指纹（每批 <= 100）
    ④ 未命中的用候选名做精确同名搜索
    ⑤ 仍不行 -> 文件名兜底（低置信，标 GUESS）
    ⑥ 同 modid / 同 sha1 合并 + 显式告警
    ⑦ 与已有清单合并 -> 原子写盘
    ⑧ 打印统计

--from-list 模式（决策 D20）：没有 jar，跳过 ①②③，全部标 GUESS，且不发起指纹请求。
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from modcheck.cli.context import AppContext
from modcheck.core.filename import is_archive_like, is_disabled_like, parse_jar_filename
from modcheck.core.hashid import sha1_of_file
from modcheck.core.jarmeta import read_jar_meta
from modcheck.core.matching import candidate_names, match_exact
from modcheck.core.models import (Detected, MatchStatus, ModEntry, ProjectHit, SourceKind)
from modcheck.errors import ConfigError, ProviderError
from modcheck.i18n import t
from modcheck.storage.profiles import (MergeStats, key_of, load_profile, merge_entries,
                                       new_profile, profile_path, save_profile)

#: 默认清单名
DEFAULT_PROFILE = "demo"
#: 单批指纹反查的哈希上限
HASH_BATCH = 100


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


# ---------------------------------------------------------------- 目录模式
def scan_dirs(directories: Sequence[Path], ctx: AppContext, *,
              known_mc_versions: Iterable[str] | None = None) -> ScanReport:
    """扫描若干目录（默认不递归），返回识别结果。"""
    report = ScanReport()
    candidates: list[tuple[Path, ModEntry]] = []
    per_dir: list[tuple[Path, list[Path], list[SkipItem], list[str]]] = []

    for raw in directories:
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
    for _directory, jars, _skipped, _subdirs in per_dir:
        for jar in jars:
            try:
                digest = sha1_of_file(jar)
            except OSError:
                continue
            digests[jar] = digest
            metas[jar] = read_jar_meta(jar)

    hash_hits = _lookup_hashes(digests, ctx, report)

    for directory, jars, skipped, subdirs in per_dir:
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
                report.skipped.append(SkipItem(jar.name, t("scan.skipped.not_mod")))
                continue
            entry = _entry_from_meta(jar, meta, digest)
            report.by_meta += 1
            report.entries.append(entry)
            candidates.append((jar, entry))

    _resolve_by_name(candidates, ctx, report)
    _merge_duplicates(report)
    return report


def _lookup_hashes(digests: dict[Path, str], ctx: AppContext,
                   report: ScanReport) -> dict[str, object]:
    """批量指纹反查；失败只记一行提示，不中断扫描。"""
    if not digests:
        return {}
    provider = None
    try:
        provider = ctx.registry.primary()
    except ProviderError:
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


def _resolve_by_name(candidates: list[tuple[Path, ModEntry]], ctx: AppContext,
                     report: ScanReport) -> None:
    """对还没有平台项目的条目做精确同名搜索（失败只降级，不中断）。"""
    if not candidates:
        return
    try:
        provider = ctx.registry.primary()
    except ProviderError:
        report.offline = True
        return
    cache: dict[str, list[ProjectHit]] = {}
    for jar, entry in candidates:
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
def scan_from_list(path: Path, ctx: AppContext, *,
                   known_mc_versions: Iterable[str] | None = None) -> ScanReport:
    """从"每行一个文件名"的文本清单导入（决策 D20：全部低置信，不发指纹请求）。"""
    target = Path(path)
    report = ScanReport()
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(t("err.from_list.missing", path=target)) from exc
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line and not line.startswith("#")]
    report.files_seen = len(lines)
    if not lines:
        raise ConfigError(t("err.from_list.missing", path=target))

    for line in lines:
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

    _resolve_by_name([(Path(e.file_name or "x.jar"), e) for e in report.entries], ctx, report)
    _merge_duplicates(report)
    return report


# ---------------------------------------------------------------- 命令入口
def run_scan(args: argparse.Namespace, ctx: AppContext) -> int:
    """scan 子命令入口；返回退出码。"""
    console = ctx.console
    profile_name = getattr(args, "profile", None) or DEFAULT_PROFILE
    from_list = getattr(args, "from_list", None)

    if from_list:
        source = Path(from_list)
        console.line(t("scan.from_list.header", path=source, lines=_count_lines(source)))
        console.line(t("scan.from_list.warn"))
        report = scan_from_list(source, ctx)
        console.line(t("scan.from_list.parsed", total=len(report.entries), named=report.guessed))
        _print_from_list_stats(report, console)
    else:
        paths = [Path(p) for p in (getattr(args, "paths", None) or [])]
        if not paths:
            raise ConfigError(t("err.scan.no_dir"))
        for directory in paths:
            console.line(t("scan.header", dir=directory))
        report = scan_dirs(paths, ctx)
        _print_dir_stats(report, console)

    if not report.entries and not report.skipped:
        console.line(t("err.dir.no_jar", path=paths[0] if not from_list else from_list))
        return 0

    profile_file = profile_path(ctx.profiles_dir, profile_name)
    existing_entries: list[ModEntry] = []
    if not getattr(args, "new", False) and profile_file.exists():
        existing_entries = load_profile(profile_file).mods
    else:
        if not profile_file.exists():
            console.line(t("scan.profile_not_exist", name=profile_name))

    merged, stats = merge_entries(existing_entries, report.entries)
    profile = new_profile(profile_name)
    if profile_file.exists() and not getattr(args, "new", False):
        profile = load_profile(profile_file)
    profile.mods = merged
    save_profile(profile, profile_file)

    _print_dupe_block(stats, console)
    console.line(t("scan.summary", profile=profile_name, added=stats.added,
                   merged=stats.merged, skipped=len(report.skipped), total=len(merged)))
    console.line(t("scan.profile_file", path=profile_file))
    return 0


def _count_lines(path: Path) -> int:
    """数一下文件行数（读不到就返回 0）。"""
    try:
        return len(path.read_text(encoding="utf-8").splitlines())
    except OSError:
        return 0


def _print_dir_stats(report: ScanReport, console) -> None:
    """打印目录模式的统计（PRD §5.8）。"""
    console.line(t("scan.read", count=report.files_seen - len(report.skipped)))
    if report.skipped:
        console.line(t("scan.skipped.header", count=len(report.skipped)))
        for item in report.skipped:
            console.line(t("scan.skipped.item", name=item.name, reason=item.reason))
    if report.subdirs:
        console.line(t("scan.subdir", count=len(report.subdirs), names="、".join(report.subdirs)))
    console.line(t("scan.identify.header"))
    console.line(t("scan.identify.hash", count=report.by_hash))
    console.line(t("scan.identify.meta", count=report.by_meta))
    console.line(t("scan.identify.search", count=report.by_search))
    if report.guessed:
        console.line(t("scan.noninteractive_unmatched", count=report.guessed))
    for warning in report.warnings:
        console.line(warning)


def _print_from_list_stats(report: ScanReport, console) -> None:
    """打印仅文件名模式的统计。"""
    matched = sum(1 for entry in report.entries if entry.sources.get("modrinth"))
    console.line(t("scan.from_list.identify_header"))
    console.line(t("scan.from_list.matched", count=matched))
    console.line(t("scan.from_list.unmatched", count=len(report.entries) - matched))
    unnamed = sum(1 for entry in report.entries if not entry.display_name)
    if unnamed:
        console.line(t("scan.from_list.unnamed", count=unnamed))
    console.line(t("scan.from_list.hint"))
    for warning in report.warnings:
        console.line(warning)


def _print_dupe_block(stats: MergeStats, console) -> None:
    """同一 modid 多文件时必须显式告警（会让服务器启动失败的真实事故）。"""
    for warning in stats.warnings:
        console.line(warning)


__all__ = ["DEFAULT_PROFILE", "HASH_BATCH", "SkipItem", "ScanReport", "scan_dirs",
           "scan_from_list", "run_scan"]
