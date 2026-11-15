"""检查报告和模组清单的 JSON 导出，以及模组清单导入。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from modcheck.core.models import Loader, ModEntry, Profile
from modcheck.core.report import Report
from modcheck.errors import ConfigError, ProfileError
from modcheck.flows.scan_flow import NoticeFn, ScanReport, save_scan_result
from modcheck.i18n import t
from modcheck.storage.atomic import atomic_text
from modcheck.storage.profiles import MergeStats

def default_filename(profile_name: str, mc: str, loader: Loader,
                     when: datetime | None = None) -> str:
    """导出文件名自动带版本与时间：report_服务器A_26.3_fabric_20261001-2103.json。"""
    stamp = (when or datetime.now()).strftime("%Y%m%d-%H%M")
    safe = "".join(ch for ch in profile_name if ch not in '\\/:*?"<>|').strip() or "profile"
    return "report_" + safe + "_" + mc + "_" + loader.value + "_" + stamp + ".json"


def _atomic_write(path: Path, text: str) -> None:
    """原子写文本文件；失败转成领域异常（PRD E22）。"""
    target = Path(path)
    try:
        with atomic_text(target, newline="") as handle:
            handle.write(text)
    except OSError as exc:
        raise ConfigError(t("err.export.failed", path=target)) from exc


def export_json(report: Report, path: Path) -> None:
    """导出 JSON（含 schema_version，供未来 GUI 消费）。"""
    _atomic_write(path, json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n")


#: 模组清单交流用的默认文件名前缀
MODLIST_PREFIX = "modlist_"


def modlist_filename(profile_name: str) -> str:
    """导出模组清单的默认文件名（与报告导出同一套命名习惯）。"""
    safe = "".join(ch for ch in profile_name if ch not in '\\/:*?"<>|').strip() or "profile"
    return MODLIST_PREFIX + safe + ".json"


def export_modlist(profile: Profile, path: Path) -> None:
    """导出可再次导入的模组清单。"""
    _atomic_write(path, json.dumps(profile.to_dict(), ensure_ascii=False, indent=2) + "\n")


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
        _check_text_list(path, index, "detected.mod_ids", detected.get("mod_ids"))
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
    flows.scan_flow.save_scan_result，保留本机已有条目的实测文件信息。

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
                               profile_name=profile_name, new=new, on_notice=on_notice,
                               refresh_files=False)
    return ImportOutcome(path=outcome.path, source=origin, merged=outcome.merged,
                         stats=outcome.stats, created=outcome.created,
                         imported=len(report.entries))


__all__ = ["default_filename", "export_json",
           "export_modlist", "modlist_filename", "MODLIST_SCHEMA_VERSION", "ImportOutcome",
           "import_modlist", "read_modlist"]
