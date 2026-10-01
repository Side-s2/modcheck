"""模组清单（profile）的读写与合并（决策 D3 + 基线 §11.6）。

规则：
  * key 三级降级：mod_id -> "sha1:<sha1>" -> normalize(display_name)；
  * 合并以 key 为准；sources 取非空、cn_name 取非空、被合并的文件名与中文名进 aliases；
  * 同一 modid 的多个 jar 必须**显式告警**（会让服务器启动失败的真实事故）；
  * 所有写盘都是原子写。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from modcheck.core.matching import normalize
from modcheck.core.models import MatchStatus, ModEntry, Profile, SourceKind
# 清单名的合法字符规则只有一份（core/profile_ops.py），这里复用，避免两处走样
from modcheck.core.profile_ops import INVALID_NAME_CHARS as _CORE_INVALID_NAME_CHARS
from modcheck.core.profile_ops import validate_profile_name as _core_validate_profile_name
from modcheck.errors import ConfigError, ProfileError
from modcheck.i18n import t

#: 清单文件名里不允许出现的字符（规则定义在 core/profile_ops.py，这里只做别名导出）
INVALID_NAME_CHARS = _CORE_INVALID_NAME_CHARS


def now_iso() -> str:
    """本地时区的 ISO-8601 时间戳（秒级）。"""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class ProfileSummary:
    """清单列表里的一行。"""

    name: str
    path: Path
    mod_count: int
    updated_at: str
    error: str = ""


@dataclass(slots=True)
class MergeStats:
    """合并统计（供 scan 输出使用）。"""

    added: int = 0
    merged: int = 0
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)


def validate_profile_name(name: str) -> None:
    """校验清单名；不合法抛 ConfigError（规则与 core/profile_ops 共用一份）。

    抛出：
        ConfigError: 空名或含非法字符。
    """
    _core_validate_profile_name(name)


def profile_path(directory: Path, name: str) -> Path:
    """清单文件路径：<dir>/<名称>.json。"""
    validate_profile_name(name)
    return Path(directory) / (name.strip() + ".json")


def list_profiles(directory: Path) -> list[ProfileSummary]:
    """列出全部清单；损坏的清单只跳过并记录，不影响其它。"""
    out: list[ProfileSummary] = []
    root = Path(directory)
    if not root.is_dir():
        return out
    for path in sorted(root.glob("*.json")):
        try:
            profile = load_profile(path)
        except ProfileError as exc:
            out.append(ProfileSummary(name=path.stem, path=path, mod_count=0,
                                      updated_at="", error=exc.message))
            continue
        out.append(ProfileSummary(name=profile.name or path.stem, path=path,
                                  mod_count=len(profile.mods), updated_at=profile.updated_at))
    return out


def load_profile(path: Path) -> Profile:
    """读取清单文件。

    抛出：
        ProfileError: 文件读不了（E11）或缺少 mods 字段（E12）。
    """
    target = Path(path)
    try:
        # 用户可能用记事本编辑过清单 -> 必须容忍 BOM
        with target.open("r", encoding="utf-8-sig") as handle:
            raw = json.load(handle)
    except FileNotFoundError as exc:
        raise ProfileError(t("err.profile.read_failed", path=target, detail=str(exc))) from exc
    except ValueError as exc:
        raise ProfileError(t("err.profile.corrupt", path=target, detail=str(exc))) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ProfileError(t("err.profile.read_failed", path=target,
                             detail=type(exc).__name__)) from exc
    if not isinstance(raw, dict) or "mods" not in raw:
        raise ProfileError(t("err.profile.schema", path=target))
    profile = Profile.from_dict(raw)
    if not profile.name:
        profile.name = target.stem
    return profile


def save_profile(profile: Profile, path: Path) -> None:
    """原子写入清单（先写 .tmp 再 os.replace）。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    profile.updated_at = now_iso()
    tmp = target.with_name(target.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(profile.to_dict(), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, target)


def new_profile(name: str, description: str = "") -> Profile:
    """新建一份空清单。"""
    validate_profile_name(name)
    stamp = now_iso()
    return Profile(name=name.strip(), description=description, created_at=stamp, updated_at=stamp)


def delete_profile(path: Path) -> None:
    """删除清单文件。"""
    Path(path).unlink(missing_ok=True)


def copy_profile(source: Path, target: Path) -> None:
    """复制清单（同时改掉内部 name 字段）。"""
    profile = load_profile(source)
    profile.name = Path(target).stem
    profile.created_at = now_iso()
    save_profile(profile, target)


def rename_profile(source: Path, target: Path) -> None:
    """重命名清单（目标已存在时拒绝）。"""
    if Path(target).exists():
        raise ProfileError(t("err.profile.rename_exists", name=Path(target).stem))
    profile = load_profile(source)
    profile.name = Path(target).stem
    save_profile(profile, target)
    delete_profile(source)


def key_of(entry: ModEntry) -> str:
    """稳定唯一键（决策 D30）。

    优先级：**平台项目标识 -> mod_id -> sha1 -> 规范化名称**。

    为什么平台标识排第一：两条识别路径（--from-list 与扫 jar）唯一能达成一致的
    东西就是"平台上的哪个项目"。实测反例：gugle-carpet-addition 的 jar 内 modid 是
    gca-wrapper、fabric-permissions-api 的 modid 是 fabric-permissions-api-v0，
    都对不上 slug；而"先导入文件名清单、再扫 jar"这种程序自己提示用户走的路径，
    只有 slug 能让两次扫描收敛到同一条记录（否则同一模组会出现两次）。
    """
    for provider in sorted(entry.sources or {}):
        slug = (entry.sources or {}).get(provider)
        if slug:
            return "slug:" + provider + ":" + str(slug).strip().lower()
    if entry.mod_id:
        return entry.mod_id.strip().lower()
    if entry.sha1:
        return "sha1:" + entry.sha1.lower()
    return normalize(entry.display_name or entry.key or entry.file_name or "unknown")


def _merge_two(keep: ModEntry, extra: ModEntry) -> ModEntry:
    """把 extra 并入 keep（原地修改 keep 并返回）。"""
    for name in (extra.file_name, extra.display_name, extra.cn_name, *extra.aliases):
        if name and name not in keep.aliases and name != keep.file_name:
            keep.aliases.append(name)
    if not keep.cn_name and extra.cn_name:
        keep.cn_name = extra.cn_name
    for provider, slug in (extra.sources or {}).items():
        if slug and not keep.sources.get(provider):
            keep.sources[provider] = slug
    if not keep.mod_id and extra.mod_id:
        keep.mod_id = extra.mod_id
    if not keep.sha1 and extra.sha1:
        keep.sha1 = extra.sha1
    if extra.detected:
        for mc in extra.detected.mc_versions:
            if mc not in keep.detected.mc_versions:
                keep.detected.mc_versions.append(mc)
        for loader in extra.detected.loaders:
            if loader not in keep.detected.loaders:
                keep.detected.loaders.append(loader)
        keep.detected.mod_version = keep.detected.mod_version or extra.detected.mod_version
    if not keep.current_version:
        keep.current_version = extra.current_version
    if keep.source_kind in (None, SourceKind.FILENAME) and extra.source_kind:
        keep.source_kind = extra.source_kind
    if keep.match_status in (MatchStatus.UNMATCHED, MatchStatus.GUESS) and extra.match_status in (
            MatchStatus.EXACT, MatchStatus.MANUAL):
        keep.match_status = extra.match_status
    note = t("scan.merged_note", file=extra.file_name or extra.display_name or extra.key)
    keep.notes = (keep.notes + "；" + note) if keep.notes else note
    return keep


def merge_entries(existing: list[ModEntry], incoming: list[ModEntry]) -> tuple[list[ModEntry], MergeStats]:
    """把 incoming 合并进 existing（幂等：合并两次结果相同）。"""
    stats = MergeStats()
    index: dict[str, ModEntry] = {}
    #: slug / sha1 / 文件名 的兜底索引：任一相同都说明是同一条记录
    aliases: dict[str, ModEntry] = {}
    result: list[ModEntry] = []

    def remember(entry: ModEntry) -> None:
        for provider, slug in (entry.sources or {}).items():
            if slug:
                aliases.setdefault("slug:" + provider + ":" + str(slug).lower(), entry)
        if entry.mod_id:
            aliases.setdefault("modid:" + entry.mod_id.strip().lower(), entry)
        if entry.sha1:
            aliases.setdefault("sha1:" + entry.sha1.lower(), entry)
        if entry.file_name:
            aliases.setdefault("file:" + entry.file_name, entry)

    for entry in existing:
        key = key_of(entry)
        entry.key = key
        if key in index:
            _merge_two(index[key], entry)
            stats.merged += 1
            stats.warnings.append(t("warn.merge.dupe_key", key=key,
                                    kept=index[key].best_name))
            continue
        index[key] = entry
        remember(entry)
        result.append(entry)

    for entry in incoming:
        key = key_of(entry)
        entry.key = key
        current = index.get(key)
        if current is None:
            current = _find_by_identity(entry, aliases)
            if current is not None:
                _merge_two(current, entry)
                remember(current)
                stats.merged += 1
                continue
        if current is None:
            index[key] = entry
            result.append(entry)
            stats.added += 1
            continue
        had_file = bool(current.file_name)
        incoming_file = entry.file_name
        if had_file and incoming_file and incoming_file != current.file_name:
            stats.warnings.append(t("warn.merge.multiple_files", modid=key,
                                    files=current.file_name + " / " + incoming_file))
        elif incoming_file and incoming_file == current.file_name:
            stats.skipped += 1
        _merge_two(current, entry)
        remember(current)
        stats.merged += 1
    return result, stats


def _find_by_identity(entry: ModEntry, aliases: dict[str, ModEntry]) -> ModEntry | None:
    """按 slug / sha1 / 文件名 找同一条记录（key 对不上时的兜底）。"""
    for provider, slug in (entry.sources or {}).items():
        if slug:
            found = aliases.get("slug:" + provider + ":" + str(slug).lower())
            if found is not None:
                return found
    if entry.mod_id:
        found = aliases.get("modid:" + entry.mod_id.strip().lower())
        if found is not None:
            return found
    if entry.sha1:
        found = aliases.get("sha1:" + entry.sha1.lower())
        if found is not None:
            return found
    if entry.file_name:
        return aliases.get("file:" + entry.file_name)
    return None


def dedupe_by_key(mods: list[ModEntry]) -> tuple[list[ModEntry], list[str]]:
    """对一份清单按 key 去重（载入时用），返回 (去重结果, 警告)。"""
    merged, stats = merge_entries(mods, [])
    return merged, stats.warnings


__all__ = ["INVALID_NAME_CHARS", "now_iso", "ProfileSummary", "MergeStats",
           "validate_profile_name", "profile_path", "list_profiles", "load_profile",
           "save_profile", "new_profile", "delete_profile", "copy_profile",
           "rename_profile", "key_of", "merge_entries", "dedupe_by_key"]
