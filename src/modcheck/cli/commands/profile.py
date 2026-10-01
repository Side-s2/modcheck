"""profile 子命令：模组清单的增删查改与重命名（功能③）。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from modcheck.cli.context import AppContext
from modcheck.console import display_width, pad, truncate
from modcheck.core.models import MatchStatus, ModEntry
from modcheck.errors import ConfigError, ProfileError
from modcheck.i18n import t
from modcheck.storage.profiles import (copy_profile, delete_profile, key_of, list_profiles,
                                       load_profile, new_profile, now_iso, profile_path,
                                       rename_profile, save_profile, validate_profile_name)

#: 支持的子操作
ACTIONS = ("list", "show", "new", "copy", "rename", "delete", "add", "remove", "edit")


def run_profile(args: argparse.Namespace, ctx: AppContext) -> int:
    """profile 子命令入口。"""
    action = (getattr(args, "action", None) or "list").lower()
    if action not in ACTIONS:
        raise ConfigError(t("config.unknown_key", key=action, keys="、".join(ACTIONS)))
    handler = globals()["_action_" + action]
    return int(handler(args, ctx))


def _require_name(args: argparse.Namespace) -> str:
    name = getattr(args, "name", None)
    if not name:
        raise ConfigError(t("err.profile.not_found", name="",
                            available=t("err.profile.none_available")))
    return str(name)


def _action_list(args: argparse.Namespace, ctx: AppContext) -> int:
    """列出全部清单。"""
    summaries = list_profiles(ctx.profiles_dir)
    if getattr(args, "json_out", False):
        ctx.console.line(json.dumps([{"name": s.name, "mods": s.mod_count,
                                      "updated_at": s.updated_at, "error": s.error}
                                     for s in summaries], ensure_ascii=False, indent=2))
        return 0
    if not summaries:
        ctx.console.line(t("profile.list.empty"))
        return 0
    ctx.console.line(t("profile.list.header", count=len(summaries), dir=ctx.profiles_dir))
    ctx.console.line()
    for index, summary in enumerate(summaries, start=1):
        if summary.error:
            ctx.console.line("  [" + str(index) + "] " + summary.name + "  " + summary.error)
            continue
        ctx.console.line(t("profile.list.item", index=index, name=summary.name,
                           count=summary.mod_count, updated=summary.updated_at[:16]))
    ctx.console.line()
    ctx.console.line(t("profile.list.hint"))
    return 0


def _action_show(args: argparse.Namespace, ctx: AppContext) -> int:
    """显示一份清单的内容。"""
    name = _require_name(args)
    path = profile_path(ctx.profiles_dir, name)
    if not path.exists():
        available = "、".join(s.name for s in list_profiles(ctx.profiles_dir))
        raise ConfigError(t("err.profile.not_found", name=name,
                            available=available or t("err.profile.none_available")))
    profile = load_profile(path)
    if getattr(args, "json_out", False):
        ctx.console.line(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2))
        return 0
    ctx.console.line(t("profile.show.header", name=profile.name, count=len(profile.mods)))
    ctx.console.line(t("profile.show.time", created=profile.created_at[:16],
                       updated=profile.updated_at[:16]))
    ctx.console.line()
    rows = [(_cell_index(index), entry.best_name, entry.mod_id or entry.key,
             str(entry.sources.get("modrinth") or "—"),
             entry.source_kind.display if entry.source_kind else "—",
             entry.current_version or "—")
            for index, entry in enumerate(profile.mods, start=1)]
    headers = (t("profile.show.col.index"), t("profile.show.col.name"),
               t("profile.show.col.modid"), t("profile.show.col.source"),
               t("profile.show.col.origin"), t("profile.show.col.version"))
    # 表头与数据行必须用**同一套列宽**组装，否则永远对不齐（CJK 必须按显示宽度算）
    widths = [max(display_width(headers[i]), *(display_width(row[i]) for row in rows)) if rows
              else display_width(headers[i]) for i in range(len(headers))]
    widths[0] = max(widths[0], 3)
    ctx.console.line(_assemble(headers, widths))
    for row in rows:
        ctx.console.line(_assemble(row, widths))
    ctx.console.line()
    ctx.console.line(t("profile.show.json_hint", name=profile.name))
    return 0


def _cell_index(index: int) -> str:
    """序号列。"""
    return str(index)


def _assemble(cells: Sequence[str], widths: Sequence[int]) -> str:
    """按列宽拼一行（显示宽度对齐，列间 2 空格）。"""
    parts = [pad(cells[0].rjust(widths[0]), widths[0])]
    for cell, width in zip(cells[1:], widths[1:]):
        parts.append(pad(truncate(cell, width), width))
    return "  " + "  ".join(parts)


def _action_new(args: argparse.Namespace, ctx: AppContext) -> int:
    """新建一份清单。"""
    name = _require_name(args)
    validate_profile_name(name)
    path = profile_path(ctx.profiles_dir, name)
    if path.exists():
        raise ConfigError(t("err.profile.exists", name=name))
    save_profile(new_profile(name, str(getattr(args, "target", None) or "")), path)
    ctx.console.line(t("profile.created", name=name))
    return 0


def _action_copy(args: argparse.Namespace, ctx: AppContext) -> int:
    """复制清单。"""
    src_name = _require_name(args)
    dst_name = str(getattr(args, "target", None) or "")
    if not dst_name:
        raise ConfigError(t("profile.name_invalid"))
    source = profile_path(ctx.profiles_dir, src_name)
    target = profile_path(ctx.profiles_dir, dst_name)
    if not source.exists():
        raise ConfigError(t("err.profile.not_found", name=src_name,
                            available=t("err.profile.none_available")))
    if target.exists():
        raise ConfigError(t("err.profile.exists", name=dst_name))
    copy_profile(source, target)
    ctx.console.line(t("profile.copied", src=src_name, dst=dst_name))
    return 0


def _action_rename(args: argparse.Namespace, ctx: AppContext) -> int:
    """重命名清单。"""
    src_name = _require_name(args)
    dst_name = str(getattr(args, "target", None) or "")
    if not dst_name:
        raise ConfigError(t("profile.name_invalid"))
    rename_profile(profile_path(ctx.profiles_dir, src_name),
                   profile_path(ctx.profiles_dir, dst_name))
    ctx.console.line(t("profile.renamed", src=src_name, dst=dst_name))
    return 0


def _action_delete(args: argparse.Namespace, ctx: AppContext) -> int:
    """删除清单（二次确认）。"""
    name = _require_name(args)
    path = profile_path(ctx.profiles_dir, name)
    if not path.exists():
        raise ConfigError(t("err.profile.not_found", name=name,
                            available=t("err.profile.none_available")))
    if ctx.interactive and ctx.prompter is not None:
        if not ctx.prompter.confirm(t("profile.delete_confirm", name=name), default=False):
            return 0
    delete_profile(path)
    ctx.console.line(t("profile.deleted", name=name))
    return 0


def _action_add(args: argparse.Namespace, ctx: AppContext) -> int:
    """往清单里加一个模组（名字来自 target 或 name）。"""
    name = _require_name(args)
    path = profile_path(ctx.profiles_dir, name)
    profile = load_profile(path) if path.exists() else new_profile(name)
    mod_name = str(getattr(args, "target", None) or "")
    if not mod_name:
        raise ConfigError(t("profile.name_invalid"))
    entry = ModEntry(key=mod_name, display_name=mod_name, added_at=now_iso(),
                     updated_at=now_iso(), match_status=MatchStatus.UNMATCHED)
    entry.key = key_of(entry)
    if any(existing.key == entry.key for existing in profile.mods):
        raise ConfigError(t("err.profile.exists", name=mod_name))
    profile.mods.append(entry)
    save_profile(profile, path)
    ctx.console.line(t("profile.added", name=mod_name, profile=name))
    return 0


def _identifiers(entry: ModEntry) -> list[str]:
    """一条记录的全部可用标识（用户输哪个都该命中）。"""
    values = [entry.key, entry.mod_id, entry.display_name, entry.cn_name, entry.file_name]
    values.extend(entry.aliases or [])
    values.extend(str(slug) for slug in (entry.sources or {}).values() if slug)
    return [str(value) for value in values if value]


def find_entry(profile, raw: str) -> tuple[ModEntry | None, list[ModEntry]]:
    """按任意标识查条目（大小写不敏感）；未命中时给出前缀候选。

    返回：
        (命中的条目或 None, 建议列表)
    """
    wanted = (raw or "").strip().lower()
    if not wanted:
        return None, []
    for entry in profile.mods:
        if any(ident.lower() == wanted for ident in _identifiers(entry)):
            return entry, []
    suggests = [entry for entry in profile.mods
                if any(wanted in ident.lower() for ident in _identifiers(entry))]
    return None, suggests


def _action_remove(args: argparse.Namespace, ctx: AppContext) -> int:
    """从清单里移除一个模组（modid / slug / 名称 / 文件名都能匹配）。"""
    name = _require_name(args)
    mod_name = str(getattr(args, "target", None) or "")
    path = profile_path(ctx.profiles_dir, name)
    profile = load_profile(path)
    entry, suggests = find_entry(profile, mod_name)
    if entry is None:
        if suggests:
            hint = "、".join(item.best_name + "（modid=" + (item.mod_id or item.key) + "）"
                             for item in suggests[:3])
            raise ConfigError(t("profile.entry_not_found_hint", profile=name, name=mod_name,
                                suggest=hint))
        raise ConfigError(t("profile.entry_not_found", profile=name, name=mod_name))
    profile.mods = [item for item in profile.mods if item is not entry]
    save_profile(profile, path)
    ctx.console.line(t("profile.removed", name=entry.best_name, profile=name))
    return 0


def _action_edit(args: argparse.Namespace, ctx: AppContext) -> int:
    """把清单里的某条改掉（--json 输出、其余场景打印路径）。"""
    name = _require_name(args)
    path = profile_path(ctx.profiles_dir, name)
    if not path.exists():
        raise ConfigError(t("err.profile.not_found", name=name,
                            available=t("err.profile.none_available")))
    profile = load_profile(path)
    save_profile(profile, path)
    ctx.console.line(t("profile.updated", name=profile.name))
    ctx.console.line(str(path))
    return 0


__all__ = ["run_profile", "ACTIONS"]
