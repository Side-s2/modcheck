"""报告导出 + **模组清单的双向读写**（导出的清单要能被导回来）。

导出（报告 / 清单）由 check --json/--md/--csv 与菜单 [3] 调用；模组清单的**导入**
是 export_modlist 的逆操作 —— 两者必须认同一份 JSON 结构（core.models.Profile 的
to_dict / from_dict），所以放在同一个模块里，分开写迟早会各认一套。
"""
from __future__ import annotations

import csv
import io
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from modcheck.core.models import Loader, ModEntry, Profile, Status
from modcheck.core.report import (Report, advice_text, build_action_hints, reason_text,
                                  summary_line, verdict_line)
from modcheck.errors import ConfigError, ProfileError
from modcheck.flows.scan_flow import NoticeFn, ScanReport, save_scan_result
from modcheck.i18n import t
from modcheck.storage.profiles import MergeStats

#: 导出的 CSV 表头（固定顺序，方便贴进表格软件）
CSV_HEADER = ("status", "reason", "key", "display_name", "cn_name", "mod_id",
              "current_version", "latest_for_loader", "latest_compat",
              "max_supported_mc", "file_name", "message")


def default_filename(profile_name: str, mc: str, loader: Loader, ext: str,
                     when: datetime | None = None) -> str:
    """导出文件名自动带版本与时间：report_服务器A_26.3_fabric_20261001-2103.json。"""
    stamp = (when or datetime.now()).strftime("%Y%m%d-%H%M")
    safe = "".join(ch for ch in profile_name if ch not in '\\/:*?"<>|').strip() or "profile"
    return "report_" + safe + "_" + mc + "_" + loader.value + "_" + stamp + "." + ext


def _atomic_write(path: Path, text: str) -> None:
    """原子写文本文件；失败转成领域异常（PRD E22）。"""
    target = Path(path)
    tmp = target.with_name(target.name + ".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp, target)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise ConfigError(t("err.export.failed", path=target)) from exc


def export_json(report: Report, path: Path) -> None:
    """导出 JSON（含 schema_version，供未来 GUI 消费）。"""
    _atomic_write(path, json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n")


def export_markdown(report: Report, path: Path) -> None:
    """导出 Markdown（可以直接贴到群里）。"""
    lines: list[str] = []
    summary = report.summary
    lines.append("# " + t("app.title"))
    lines.append("")
    lines.append("- " + t("report.header.profile", name=report.profile_name,
                          count=summary["total_all"]))
    lines.append("- " + t("report.header.target", mc=report.mc_version,
                          loader=report.loader.display_name))
    lines.append("- " + t("report.header.time", time=report.generated_at,
                          elapsed=f"{report.elapsed:.0f}", requests=report.requests_made,
                          cache_hits=report.cache_hits))
    lines.append("")
    lines.append("**" + verdict_line(report) + "**")
    lines.append("")
    for status in (Status.BLOCKED, Status.DEGRADED, Status.UNKNOWN, Status.READY, Status.IGNORED):
        group = report.groups.get(status, [])
        if not group:
            continue
        lines.append("## " + t("group." + status.value + ".title", count=len(group),
                               mc=report.mc_version, loader=report.loader.display_name))
        lines.append("")
        lines.append("| # | 名称 | modid | 当前版本 | 原因 |")
        lines.append("|---|---|---|---|---|")
        for index, item in enumerate(group, start=1):
            lines.append("| " + str(index) + " | " + item.mod.best_name + " | "
                         + (item.mod.mod_id or item.mod.key) + " | "
                         + (item.current_version or "-") + " | "
                         + reason_text(item, report).replace("|", "/") + " |")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(summary_line(report))
    lines.append("")
    lines.append("\`\`\`")
    lines.extend(build_action_hints(report))
    lines.append("\`\`\`")
    _atomic_write(path, "\n".join(lines) + "\n")


def export_csv(report: Report, path: Path) -> None:
    """导出 CSV（UTF-8 BOM 让 Excel 正确识别中文）。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_HEADER)
    for item in report.iter_items():
        writer.writerow([
            item.status.value,
            item.reason.value,
            item.mod.key,
            item.mod.display_name,
            item.mod.cn_name or "",
            item.mod.mod_id or "",
            item.current_version or "",
            item.latest_for_loader.version_number if item.latest_for_loader else "",
            item.latest_compat.version_number if item.latest_compat else "",
            item.max_supported_mc or "",
            item.mod.file_name or "",
            (reason_text(item, report) + " / " + advice_text(item, report)).replace("\n", " "),
        ])
    _atomic_write(path, "\ufeff" + buffer.getvalue())


#: 模组清单交流用的默认文件名前缀
MODLIST_PREFIX = "modlist_"


def modlist_filename(profile_name: str, ext: str) -> str:
    """导出模组清单的默认文件名（与报告导出同一套命名习惯）。"""
    safe = "".join(ch for ch in profile_name if ch not in '\\/:*?"<>|').strip() or "profile"
    return MODLIST_PREFIX + safe + "." + ext


def export_modlist(profile, path: Path, *, fmt: str = "md") -> None:
    """导出**模组清单**（供服主之间交流）。

    与报告导出（export_markdown 等）**不是一回事**：
      · 报告是一次检查的结果，带状态与建议；
      · 清单只是「我这个包里有哪些模组」，与查没查过无关。
    所以这里**不下任何结论**，只列事实，外加一个能点开的链接 ——
    对方拿到后可以照着装，也可以把 JSON 那份导回自己的工具里。
    """
    target = Path(path)
    mods = list(profile.mods)
    if fmt == "json":
        _atomic_write(target, json.dumps(profile.to_dict(), ensure_ascii=False, indent=2) + "\n")
        return

    lines = [f"# 模组清单：{profile.name}", ""]
    if getattr(profile, "description", ""):
        lines += [profile.description, ""]
    ignored = sum(1 for e in mods if str(getattr(e, "match_status", "")) == "MatchStatus.IGNORED")
    lines.append(f"共 {len(mods)} 个模组。" + (f"其中 {ignored} 个已标记为忽略。" if ignored else ""))
    lines += ["", "| # | 模组 | 平台项目 | 文件名 |", "|---|------|---------|--------|"]
    for i, entry in enumerate(mods, start=1):
        name = (getattr(entry, "display_name", "") or getattr(entry, "cn_name", "")
                or getattr(entry, "file_name", "") or getattr(entry, "key", ""))
        slug = (getattr(entry, "sources", None) or {}).get("modrinth") or ""
        link = f"[{slug}](https://modrinth.com/mod/{slug})" if slug else "（未识别）"
        lines.append(f"| {i} | {name} | {link} | {getattr(entry, 'file_name', '') or ''} |")
    lines += ["", "> 本清单由 modcheck 导出，不含任何检查结论。", ""]
    _atomic_write(target, "\n".join(lines))


# ---------------------------------------------------------------- 模组清单导入
#: 本工具导出的 JSON 清单使用的格式版本（必须与 core.models.Profile 一致，有测试盯着）
MODLIST_SCHEMA_VERSION = 1

#: 清单条目的文本字段。类型不对时，合并那一步会把数字当文件名去拼字符串（TypeError），
#: 所以读入时就要挡住 —— 错的类型是"文件坏"，不是"少一条信息"。
_ENTRY_TEXT_FIELDS = ("key", "display_name", "cn_name", "mod_id", "file_name", "sha1",
                      "current_version", "notes", "added_at", "updated_at")


@dataclass(frozen=True, slots=True)
class ImportOutcome:
    """一次清单导入的结果（纯数据，CLI / GUI 各自决定怎么显示）。"""

    #: 写入的清单文件
    path: Path
    #: 被导入的清单文件；调用方直接传 Profile 时为 None
    source: Path | None
    #: 合并后的全部条目（已有 + 导入）
    merged: list[ModEntry]
    #: 合并统计（新增 / 合并 / 重复文件名告警）
    stats: MergeStats
    #: 目标清单此前不存在（据此说一句"已新建一个"）
    created: bool
    #: 导入文件里的条目数
    imported: int


def _kind_of(value: object) -> str:
    """JSON 值的类型名（中文说法取自 i18n，本模块不写中文字面量）。"""
    if value is None:
        name = "null"
    elif isinstance(value, bool):
        name = "bool"
    elif isinstance(value, (int, float)):
        name = "number"
    elif isinstance(value, str):
        name = "text"
    elif isinstance(value, (list, tuple)):
        name = "list"
    elif isinstance(value, dict):
        name = "dict"
    else:
        name = "other"
    return t("json.kind." + name)


def _entry_error(path: Path, index: int, reason: str) -> ProfileError:
    """条目结构错误的统一说法：第几条 + 为什么 + 哪个文件。"""
    return ProfileError(t("err.import.entry", index=index, reason=reason, path=path))


def _raise_field(path: Path, index: int, field: str, expected: str, value: object) -> None:
    """某个字段的类型不对（expected 是 json.expected.* 的文案 key）。"""
    raise _entry_error(path, index, t("err.import.entry.field", field=field,
                                      expected=t(expected), kind=_kind_of(value)))


def _check_text_list(path: Path, index: int, field: str, value: object) -> None:
    """校验"文本列表"字段：可以没有，但有就必须是文本列表。"""
    if value is None:
        return
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        _raise_field(path, index, field, "json.expected.text_list", value)


def _has_identity(raw: dict) -> bool:
    """这条记录能不能被认出来（认不出来就会和别的空条目挤成同一条）。"""
    for field in ("key", "display_name", "mod_id", "file_name", "sha1"):
        if str(raw.get(field) or "").strip():
            return True
    return any(str(slug or "").strip() for slug in (raw.get("sources") or {}).values())


def _check_entry(raw: object, index: int, path: Path) -> None:
    """逐字段检查一条记录，保证 core.models.ModEntry.from_dict 读到的都是预期的类型。

    为什么必须这么严：读自己的清单时"少一个字段"只是少一条信息，而"字段类型不对"
    会一路传到合并与检查里炸掉。这里挡住，用户看到的是
    「第 3 条记录的「file_name」应为文本，实际是数字」，而不是一个 Python 异常。
    """
    if not isinstance(raw, dict):
        raise _entry_error(path, index, t("err.import.entry.not_object", kind=_kind_of(raw)))
    for field in _ENTRY_TEXT_FIELDS:
        value = raw.get(field)
        if value is not None and not isinstance(value, str):
            _raise_field(path, index, field, "json.expected.text", value)
    _check_text_list(path, index, "aliases", raw.get("aliases"))
    sources = raw.get("sources")
    if sources is not None:
        if not isinstance(sources, dict) or any(
                not isinstance(name, str) or (slug is not None and not isinstance(slug, str))
                for name, slug in sources.items()):
            _raise_field(path, index, "sources", "json.expected.text_map", sources)
    detected = raw.get("detected")
    if detected is not None:
        if not isinstance(detected, dict):
            _raise_field(path, index, "detected", "json.expected.dict", detected)
        _check_text_list(path, index, "detected.mc_versions", detected.get("mc_versions"))
        _check_text_list(path, index, "detected.loaders", detected.get("loaders"))
        version = detected.get("mod_version")
        if version is not None and not isinstance(version, str):
            _raise_field(path, index, "detected.mod_version", "json.expected.text", version)
    if not _has_identity(raw):
        raise _entry_error(path, index, t("err.import.entry.no_name"))


def read_modlist(path: Path) -> Profile:
    """读入并**严格校验**一份 JSON 模组清单。

    与 storage.profiles.load_profile 的区别：
      · load_profile 读的是**自己的**清单，尽量宽容（坏了也只在清单列表里标一行错误）；
      · 这里读的是**别人发来的**文件，必须当场说清楚它为什么不是本工具的清单 ——
        绝不能把一份别家的 JSON 当成空清单合并进用户的清单里。
    返回的 Profile 只用来取条目与清单名，不会被当成"用户自己的清单文件"直接写回。

    抛出：
        ProfileError: 文件不存在 / 不是 JSON / 不是本工具的清单 / 格式版本不支持 /
            条目结构不对。每条都带可直接展示给用户的中文说明（E12 的处理方式）。
    """
    target = Path(path)
    try:
        # 对方可能用记事本打开并保存过这份清单 -> 同样容忍 BOM（与 load_profile 一致）
        with target.open("r", encoding="utf-8-sig") as handle:
            raw = json.load(handle)
    except FileNotFoundError as exc:
        raise ProfileError(t("err.import.missing", path=target)) from exc
    except ValueError as exc:
        raise ProfileError(t("err.import.corrupt", path=target, detail=str(exc))) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ProfileError(t("err.import.read_failed", path=target,
                             detail=type(exc).__name__)) from exc
    if not isinstance(raw, dict) or "mods" not in raw:
        raise ProfileError(t("err.import.schema", path=target))
    version = raw.get("schema_version", MODLIST_SCHEMA_VERSION)
    if isinstance(version, bool) or not isinstance(version, int):
        raise ProfileError(t("err.import.version_bad", path=target, kind=_kind_of(version)))
    if version != MODLIST_SCHEMA_VERSION:
        raise ProfileError(t("err.import.version", path=target, found=version,
                             supported=MODLIST_SCHEMA_VERSION))
    mods = raw.get("mods")
    if not isinstance(mods, list):
        raise ProfileError(t("err.import.mods_type", path=target, kind=_kind_of(mods)))
    for index, item in enumerate(mods, start=1):
        _check_entry(item, index, target)
    # 字段映射只有一份（core.models.Profile.from_dict），这里不另写一套
    return Profile.from_dict(raw)


def import_modlist(source: "Path | str | Profile", *, profiles_dir: Path, profile_name: str,
                   new: bool = False, on_notice: NoticeFn | None = None) -> ImportOutcome:
    """把别人导出的 JSON 清单合并进本机清单（不存在则新建）。

    合并规则**不在这里**：导入的条目先装成 ScanReport，再交给
    flows.scan_flow.save_scan_result —— 与扫描落盘共用同一份 merge_entries。
    于是"扫描进来的"与"导入进来的"条目走的是同一套规则，不可能各有一套。

    参数：
        source: 要导入的清单文件路径；也可以直接传已经读好的 Profile（避免重读一次）。
        profiles_dir: 本机清单目录（CLI 传 ctx.profiles_dir）。
        profile_name: 合并进哪份清单；不存在则按这个名字新建。
        new: True 表示忽略已有清单，整份替换（与 scan --new 同义）。
        on_notice: 提示回调，原样透传给 save_scan_result（"将新建一个"那句）。

    抛出：
        ProfileError: 源文件校验不过（见 read_modlist），或目标清单写不进去。
        ConfigError: 清单名不合法。
    """
    if isinstance(source, Profile):
        origin, profile = None, source
    else:
        origin = Path(source)
        profile = read_modlist(origin)
    report = ScanReport(entries=list(profile.mods))
    outcome = save_scan_result(report, profiles_dir=Path(profiles_dir),
                               profile_name=profile_name, new=new, on_notice=on_notice)
    return ImportOutcome(path=outcome.path, source=origin, merged=outcome.merged,
                         stats=outcome.stats, created=outcome.created,
                         imported=len(report.entries))


__all__ = ["default_filename", "export_json", "export_markdown", "export_csv", "CSV_HEADER",
           "export_modlist", "modlist_filename", "MODLIST_SCHEMA_VERSION", "ImportOutcome",
           "import_modlist", "read_modlist"]
