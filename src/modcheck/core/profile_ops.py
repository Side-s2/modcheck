"""清单的纯函数操作（PRD §13.1，R3-A01）。

硬性约束（PRD §13.1 的分层契约）：
  * 不 import storage / providers、不写盘、不 print / input / sys.exit；
  * 每个函数都返回**新的** Profile，绝不原地修改入参；
  * 条目定位沿用裁决 D33 的全标识顺序（大小写不敏感）：
    key → mod_id → sources 各 slug → display_name → cn_name → file_name/aliases，
    另外额外支持 1 起算的**编号**（PRD §13.2 的「编号 / 模组名 / modid」三合一输入）。

「返回新对象」这条不只是洁癖：CLI 的规则是「写盘失败则内存与磁盘都不变」，
调用方只要在保存成功后才采用新对象，这条规则就天然成立（见 R3-A13）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Final, Sequence
from urllib.parse import unquote, urlsplit

from modcheck.core.matching import normalize
from modcheck.core.models import MatchStatus, ModEntry, Profile
from modcheck.errors import ConfigError
from modcheck.i18n import t

#: 清单名里不允许出现的字符（Windows 与 Linux 都不安全）；storage 复用这一份。
#: chr(34)=双引号、chr(92)=反斜杠：写成转义序列在源码里极易看错，这里刻意用 chr()。
INVALID_NAME_CHARS: Final[tuple[str, ...]] = (
    chr(92), "/", ":", "*", "?", chr(34), "<", ">", "|",
)

#: 一页多少个模组（PRD §13.2）
PAGE_SIZE: Final[int] = 20

#: 定位结果的三种原因（与 ResolveResult.reason_key 对应）
REASON_FOUND: Final[str] = "found"
REASON_NOT_FOUND: Final[str] = "not_found"
REASON_AMBIGUOUS: Final[str] = "ambiguous"

#: 候选建议最多给几条（PRD §13.2 的「你要找的是不是…？」）
MAX_SUGGESTS: Final[int] = 3

#: D33 的 6 级标识（顺序即优先级，不许调整）
IDENTIFIER_LEVELS: Final[int] = 6


def now_iso() -> str:
    """本地时区的 ISO-8601 时间戳（秒级）。

    与 storage.profiles.now_iso() 同格式；core 不许 import storage，
    所以这里独立实现一份（两边格式一致，测试里互相校验）。
    """
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def validate_profile_name(name: str) -> None:
    """校验清单名；不合法抛 ConfigError（与 storage 侧同一句文案）。

    抛出：
        ConfigError: 空名或含非法字符。
    """
    text = (name or "").strip()
    if not text or any(ch in text for ch in INVALID_NAME_CHARS):
        raise ConfigError(t("profile.name_invalid"))


@dataclass(frozen=True, slots=True)
class OpResult:
    """一次清单操作的结果（PRD §13.1 契约）。

    参数：
        changed: 是否真的改了内容（False 时调用方**不要**写盘）。
        profile: 新的 Profile（changed 为 False 时就是原对象）。
        message_key: 给用户看的那句文案的 i18n key。
        message_args: 文案的占位符实参。
        warnings: 需要额外展示的提醒（例如没找到的定位串）。
    """

    changed: bool
    profile: Profile
    message_key: str = ""
    message_args: dict[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolveResult:
    """按标识定位条目的结果。

    参数：
        entry: 唯一命中时的那条；未命中/多命中时为 None。
        candidates: 多命中时的全部命中项，或未命中时的候选建议。
        reason_key: found / not_found / ambiguous。
    """

    entry: ModEntry | None
    candidates: tuple[ModEntry, ...] = ()
    reason_key: str = REASON_FOUND


def _ident_values(entry: ModEntry, level: int) -> list[str]:
    """按 D33 优先级返回第 level 级的全部标识值。"""
    if level == 0:
        return [entry.key]
    if level == 1:
        return [entry.mod_id or ""]
    if level == 2:
        return [str(slug) for slug in (entry.sources or {}).values() if slug]
    if level == 3:
        return [entry.display_name]
    if level == 4:
        return [entry.cn_name or ""]
    return [entry.file_name or "", *(entry.aliases or [])]


def entry_identifiers(entry: ModEntry) -> list[str]:
    """一条记录的全部可用标识（按优先级、去重、去空）。"""
    out: list[str] = []
    for level in range(IDENTIFIER_LEVELS):
        for value in _ident_values(entry, level):
            text = str(value or "").strip()
            if text and text not in out:
                out.append(text)
    return out


def resolve_selector(profile: Profile, selector: str) -> ResolveResult:
    """按标识定位一条记录（D33 顺序 + 1 起算的编号）。

    参数：
        profile: 要查找的清单。
        selector: 用户输入的编号 / 名称 / modid / slug / 文件名。
    返回：
        ResolveResult；未命中时 candidates 是模糊匹配到的候选建议。
    """
    text = (selector or "").strip()
    if not text:
        return ResolveResult(None, (), REASON_NOT_FOUND)
    mods = list(profile.mods)
    if text.isdigit():
        index = int(text)
        if 1 <= index <= len(mods):
            return ResolveResult(mods[index - 1], (), REASON_FOUND)
        # 编号越界不报错，继续按标识找：用户完全可能真有个叫 3 的模组
    wanted = text.lower()
    for level in range(IDENTIFIER_LEVELS):
        hits = [entry for entry in mods
                if any(str(value).strip().lower() == wanted
                       for value in _ident_values(entry, level) if value)]
        if len(hits) == 1:
            return ResolveResult(hits[0], (), REASON_FOUND)
        if len(hits) > 1:
            return ResolveResult(None, tuple(hits), REASON_AMBIGUOUS)
    return ResolveResult(None, tuple(_suggest(mods, wanted)), REASON_NOT_FOUND)


def _suggest(mods: Sequence[ModEntry], wanted: str) -> list[ModEntry]:
    """模糊候选建议（输入串是某个标识的子串），最多 MAX_SUGGESTS 条。"""
    out: list[ModEntry] = []
    for entry in mods:
        if any(wanted in value.lower() for value in entry_identifiers(entry)):
            out.append(entry)
        if len(out) >= MAX_SUGGESTS:
            break
    return out


def clone_entry(entry: ModEntry) -> ModEntry:
    """深拷贝一条记录（经 to_dict/from_dict，保证 sources / aliases 不共享）。"""
    return ModEntry.from_dict(entry.to_dict())


def _new_profile(profile: Profile, mods: Sequence[ModEntry]) -> Profile:
    """用新的模组列表造一份新清单（updated_at 刷新）。"""
    return Profile(schema_version=profile.schema_version, name=profile.name,
                   description=profile.description, created_at=profile.created_at,
                   updated_at=now_iso(), mods=list(mods))


def _existing_keys(profile: Profile) -> set[str]:
    """已有的 key 集合（新增时判重用）。"""
    return {str(entry.key).strip().lower() for entry in profile.mods if entry.key}


def remove_mods(profile: Profile, selectors: Sequence[str]) -> OpResult:
    """按标识删除若干模组，返回新清单。

    参数：
        profile: 原清单（不被修改）。
        selectors: 编号 / modid / 名称 / slug / 文件名，可多个。
    返回：
        OpResult；一个都没删掉时 changed=False（调用方不要写盘）。
    """
    targets: list[ModEntry] = []
    missing: list[str] = []
    for raw in selectors:
        text = (raw or "").strip()
        if not text:
            continue
        result = resolve_selector(profile, text)
        if result.entry is None:
            missing.append(text)
            continue
        if not any(item is result.entry for item in targets):
            targets.append(result.entry)
    if not targets:
        return OpResult(False, profile, "manage.remove.none",
                        {"profile": profile.name}, tuple(missing))
    keep = [entry for entry in profile.mods
            if not any(entry is target for target in targets)]
    new_profile = _new_profile(profile, keep)
    return OpResult(True, new_profile, "manage.remove.done",
                    {"count": str(len(targets)), "profile": profile.name,
                     "left": str(len(keep))}, tuple(missing))


def set_source(profile: Profile, selector: str, *, provider: str, slug: str,
               title: str = "") -> OpResult:
    """把某条记录指定到平台项目（写 sources + match_status=manual）。

    参数：
        profile: 原清单。
        selector: 定位串（编号 / 名称 / modid / 文件名）。
        provider: 数据源机器名（本期只有 modrinth）。
        slug: 平台项目标识（统一写 slug，见裁决 D38）。
        title: 平台项目标题（只用于文案）。
    """
    result = resolve_selector(profile, selector)
    if result.entry is None:
        return OpResult(False, profile, "manage.source.entry_missing",
                        {"selector": selector})
    target = result.entry
    entry = clone_entry(target)
    entry.sources = dict(entry.sources or {})
    entry.sources[str(provider)] = str(slug)
    entry.match_status = MatchStatus.MANUAL
    # key 首选平台标识（D30）：不改的话去重/合并会与 D38 的「统一写 slug」打架
    entry.key = "slug:" + str(provider) + ":" + str(slug).strip().lower()
    entry.updated_at = now_iso()
    mods = [entry if item is target else item for item in profile.mods]
    new_profile = _new_profile(profile, mods)
    return OpResult(True, new_profile, "manage.source.done",
                    {"name": target.best_name, "title": title or str(slug),
                     "slug": str(slug)})


def set_ignored(profile: Profile, selector: str, ignored: bool) -> OpResult:
    """忽略 / 取消忽略某条记录（幂等：状态没变时 changed=False）。

    取消忽略时恢复到「手动指定」（有平台标识）或「未匹配」（没有平台标识）——
    这两态在检查流程里都会正常判定（core/checker_run.py 只看 IGNORED）。
    """
    result = resolve_selector(profile, selector)
    if result.entry is None:
        return OpResult(False, profile, "manage.ignore.entry_missing",
                        {"selector": selector})
    target = result.entry
    has_source = any((target.sources or {}).values())
    wanted = MatchStatus.IGNORED if ignored else (
        MatchStatus.MANUAL if has_source else MatchStatus.UNMATCHED)
    key = "manage.ignore.done" if ignored else "manage.ignore.undone"
    args = {"name": target.best_name}
    if target.match_status is wanted:
        return OpResult(False, profile, key, args)
    entry = clone_entry(target)
    entry.match_status = wanted
    entry.updated_at = now_iso()
    mods = [entry if item is target else item for item in profile.mods]
    return OpResult(True, _new_profile(profile, mods), key, args)


def add_mod(profile: Profile, *, display_name: str, mod_id: str | None = None,
            source_slug: str | None = None) -> OpResult:
    """新增一条模组记录（空名 / 重名各自给文案）。

    参数：
        profile: 原清单。
        display_name: 展示名（必填）。
        mod_id: jar 内的 modid（可选）。
        source_slug: Modrinth 项目标识（可选；给了就按 D30 生成 slug 键）。
    """
    name = (display_name or "").strip()
    if not name:
        return OpResult(False, profile, "manage.add.empty", {})
    entry = ModEntry(key="", display_name=name, mod_id=(mod_id or "").strip() or None,
                     match_status=MatchStatus.UNMATCHED, added_at=now_iso(),
                     updated_at=now_iso())
    slug = (source_slug or "").strip()
    if slug:
        entry.sources = {"modrinth": slug}
        entry.match_status = MatchStatus.MANUAL
        entry.key = "slug:modrinth:" + slug.lower()
    elif entry.mod_id:
        entry.key = entry.mod_id.lower()
    else:
        entry.key = normalize(name)
    if entry.key.lower() in _existing_keys(profile):
        return OpResult(False, profile, "manage.add.exists", {"name": name})
    return OpResult(True, _new_profile(profile, [*profile.mods, entry]),
                    "manage.add.done", {"name": name, "profile": profile.name})


def rename(profile: Profile, new_name: str) -> OpResult:
    """重命名清单（只改内存对象里的 name；文件改名由调用方交给 storage）。

    抛出：
        ConfigError: 名称非法（空或含非法字符）。
    """
    validate_profile_name(new_name)
    text = new_name.strip()
    if text == profile.name:
        return OpResult(False, profile, "manage.rename.same", {"name": text})
    old = profile.name
    renamed = Profile(schema_version=profile.schema_version, name=text,
                      description=profile.description, created_at=profile.created_at,
                      updated_at=now_iso(), mods=list(profile.mods))
    return OpResult(True, renamed, "manage.rename.done", {"old": old, "new": text})


def page_of(profile: Profile, page: int, *, size: int = PAGE_SIZE) -> tuple[list[ModEntry], int]:
    """取第 page 页（1 起算）的模组与总页数。

    空清单也算 1 页；page 越界会被夹到 [1, 总页数]（调用方另有「已经是最后一页」提示）。
    """
    step = max(1, int(size))
    mods = list(profile.mods)
    pages = max(1, (len(mods) + step - 1) // step)
    index = min(max(1, int(page)), pages)
    return mods[(index - 1) * step: index * step], pages


#: Modrinth 项目 slug 的合法形状（小写字母/数字起头，后面可带 . _ -）
_SLUG_CHARS: Final[str] = "abcdefghijklmnopqrstuvwxyz0123456789._-"


def parse_project_selector(raw: str) -> str | None:
    """把用户输入解析成平台项目 slug（PRD §13.2 的「slug 或链接」）。

    支持：carpet / https://modrinth.com/mod/carpet / 带尾斜杠 / 带查询串 /
    /project/<slug>。非法输入返回 None（调用方给「不像项目名或链接」的提示，绝不猜）。
    """
    text = (raw or "").strip()
    if not text:
        return None
    if "://" in text or text.lower().startswith(("modrinth.com/", "www.modrinth.com/")):
        parts = urlsplit(text if "://" in text else "https://" + text)
        if parts.scheme not in ("http", "https"):
            return None
        if parts.netloc.lower() not in ("modrinth.com", "www.modrinth.com"):
            return None
        segments = [unquote(item) for item in parts.path.split("/") if item]
        for index, segment in enumerate(segments[:-1]):
            if segment in ("mod", "project", "datapack", "plugin"):
                return _clean_slug(segments[index + 1])
        return None
    return _clean_slug(text)


def _clean_slug(text: str) -> str | None:
    """校验并规范化一个 slug（Modrinth 的 slug 全小写，含字母数字与 . _ -）。"""
    slug = (text or "").strip().lower()
    if not slug or len(slug) > 64:
        return None
    if slug[0] not in _SLUG_CHARS[:36]:
        return None
    if any(ch not in _SLUG_CHARS for ch in slug):
        return None
    return slug


__all__ = [
    "INVALID_NAME_CHARS", "PAGE_SIZE", "REASON_FOUND", "REASON_NOT_FOUND",
    "REASON_AMBIGUOUS", "MAX_SUGGESTS", "IDENTIFIER_LEVELS",
    "OpResult", "ResolveResult", "now_iso", "validate_profile_name",
    "entry_identifiers", "resolve_selector", "clone_entry", "remove_mods",
    "set_source", "set_ignored", "add_mod", "rename", "page_of",
    "parse_project_selector",
]
