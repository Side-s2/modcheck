"""数据模型（纯数据，可 JSON 双向序列化）。

本模块只描述结构，不含任何 I/O 与业务判断。所有值对象用 frozen dataclass，
可变聚合（Profile / ModEntry / Settings）用 slots dataclass 并提供 to_dict/from_dict。

重要约束：
  * VersionInfo.date_published 原样保存 ISO 字符串，**禁止**自行解析或排序
    （基线实测：日期会并列，排序会引入不稳定，判定只准用 API 返回的顺序）。
  * ProjectInfo.version_count 只用于区分「项目已废」与「没有你这个加载器」，
    **绝不**用于判断最新版（基线 §17.8：/project 的 versions[] 不是倒序）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from modcheck.errors import ConfigError
from modcheck.i18n import t


class Loader(str, Enum):
    """服务端加载器（本期只做三个，用枚举便于以后加 Quilt）。"""

    FABRIC = "fabric"
    NEOFORGE = "neoforge"
    FORGE = "forge"

    @property
    def display_name(self) -> str:
        """界面上显示的加载器名（First-letter 大写形式）。"""
        return _LOADER_DISPLAY[self.value]

    @classmethod
    def parse(cls, raw: str) -> "Loader":
        """把用户输入解析成 Loader（大小写不敏感）。

        抛出：
            ConfigError: 不是受支持的加载器。
        """
        key = (raw or "").strip().lower()
        for loader in cls:
            if loader.value == key:
                return loader
        raise ConfigError(t("err.loader.unsupported", value=raw))


_LOADER_DISPLAY: Final[dict[str, str]] = {
    "fabric": "Fabric",
    "neoforge": "NeoForge",
    "forge": "Forge",
}


class Status(str, Enum):
    """报告分组状态（四态 + 已忽略）。"""

    READY = "ready"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"
    IGNORED = "ignored"

    @property
    def display(self) -> str:
        """状态的中文名（就绪 / 需降级 / 阻塞 / 未判定 / 已忽略）。"""
        return t("status." + self.value)


class ReasonCode(str, Enum):
    """判定原因码；取值必须与基线 §7 的表格逐字一致。"""

    OK = "OK"
    OLD_VERSION_ONLY = "OLD_VERSION_ONLY"
    PRERELEASE_ONLY = "PRERELEASE_ONLY"
    NO_LOADER = "NO_LOADER"
    NO_MC_VERSION = "NO_MC_VERSION"
    NOT_FOUND = "NOT_FOUND"
    NO_FILES = "NO_FILES"
    ERROR = "ERROR"
    UNMATCHED = "UNMATCHED"
    IGNORED = "IGNORED"
    MC_VERSION_FUZZY = "MC_VERSION_FUZZY"  # 预留：本期不启用宽松匹配


class MatchStatus(str, Enum):
    """模组与平台项目的匹配状态。"""

    EXACT = "exact"
    MANUAL = "manual"
    UNMATCHED = "unmatched"
    IGNORED = "ignored"
    GUESS = "guess"


class SourceKind(str, Enum):
    """识别来源（报告头要统计这四类）。"""

    HASH = "hash"
    JAR_META = "jar_meta"
    SEARCH = "search"
    FILENAME = "filename"

    @property
    def display(self) -> str:
        """识别来源的中文名。"""
        return t("source." + self.value)


@dataclass(frozen=True, slots=True)
class FileInfo:
    """版本里的一个文件。"""

    filename: str
    url: str
    primary: bool
    size: int
    hashes: dict[str, str]

    def to_dict(self, *, sha1_only: bool = False) -> dict[str, Any]:
        """序列化；sha1_only=True 时只保留 sha1（缓存瘦身用）。"""
        hashes = self.hashes
        if sha1_only:
            hashes = {k: v for k, v in self.hashes.items() if k == "sha1"}
        return {"filename": self.filename, "url": self.url, "primary": self.primary,
                "size": self.size, "hashes": dict(hashes)}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "FileInfo":
        """从字典还原（未知字段忽略）。"""
        return cls(
            filename=str(raw.get("filename", "")),
            url=str(raw.get("url", "")),
            primary=bool(raw.get("primary", False)),
            size=int(raw.get("size", 0) or 0),
            hashes={str(k): str(v) for k, v in dict(raw.get("hashes") or {}).items()},
        )


@dataclass(frozen=True, slots=True)
class VersionInfo:
    """平台上的一个版本条目。"""

    version_id: str
    version_number: str
    name: str
    project_id: str
    date_published: str
    version_type: str
    game_versions: tuple[str, ...]
    loaders: tuple[str, ...]
    files: tuple[FileInfo, ...]

    @property
    def is_release(self) -> bool:
        """是否为正式版通道。"""
        return self.version_type == "release"

    @property
    def primary_file(self) -> FileInfo | None:
        """主文件：primary 为真者，否则第一个。"""
        for item in self.files:
            if item.primary:
                return item
        return self.files[0] if self.files else None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "VersionInfo":
        """从 Modrinth /version 的原始 JSON 构造。"""
        return cls(
            version_id=str(raw.get("id", "")),
            version_number=str(raw.get("version_number", "")),
            name=str(raw.get("name", "")),
            project_id=str(raw.get("project_id", "")),
            date_published=str(raw.get("date_published", "")),
            version_type=str(raw.get("version_type", "")),
            game_versions=tuple(str(v) for v in (raw.get("game_versions") or ())),
            loaders=tuple(str(v) for v in (raw.get("loaders") or ())),
            files=tuple(FileInfo.from_dict(f) for f in (raw.get("files") or ())),
        )

    def to_cache(self) -> dict[str, Any]:
        """缓存用的精简结构（只留判定与展示需要的字段）。"""
        return {
            "id": self.version_id,
            "project_id": self.project_id,
            "version_number": self.version_number,
            "name": self.name,
            "date_published": self.date_published,
            "version_type": self.version_type,
            "game_versions": list(self.game_versions),
            "loaders": list(self.loaders),
            "files": [f.to_dict(sha1_only=True) for f in self.files],
        }

    @classmethod
    def from_cache(cls, raw: dict[str, Any]) -> "VersionInfo":
        """从精简缓存结构还原。"""
        return cls.from_api(raw)

    def to_dict(self) -> dict[str, Any]:
        """完整序列化（导出报告用）。"""
        return {
            "id": self.version_id,
            "version_number": self.version_number,
            "name": self.name,
            "project_id": self.project_id,
            "date_published": self.date_published,
            "version_type": self.version_type,
            "game_versions": list(self.game_versions),
            "loaders": list(self.loaders),
            "files": [f.to_dict() for f in self.files],
        }


@dataclass(frozen=True, slots=True)
class ProjectHit:
    """搜索命中的一条项目。"""

    project_id: str
    slug: str
    title: str
    downloads: int
    description: str
    provider: str


    @classmethod
    def from_api(cls, raw: dict[str, Any], *, provider: str = "modrinth") -> "ProjectHit":
        """从 Modrinth /search 的一条结果构造。"""
        return cls(
            project_id=str(raw.get("project_id", "")),
            slug=str(raw.get("slug", "")),
            title=str(raw.get("title", "")),
            downloads=int(raw.get("downloads", 0) or 0),
            description=str(raw.get("description", "")),
            provider=provider,
        )

    def to_dict(self) -> dict[str, Any]:
        """序列化。"""
        return {"project_id": self.project_id, "slug": self.slug, "title": self.title,
                "downloads": self.downloads, "description": self.description,
                "provider": self.provider}


@dataclass(frozen=True, slots=True)
class ProjectInfo:
    """项目详情。"""

    project_id: str
    slug: str
    title: str
    description: str
    project_type: str
    loaders: tuple[str, ...]
    game_versions: tuple[str, ...]
    downloads: int
    version_count: int


    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "ProjectInfo":
        """从 Modrinth /project 的响应构造。

        注意：versions 只用来数长度，**绝不**用来判断最新版（基线 §17.8）。
        """
        versions = raw.get("versions") or []
        return cls(
            project_id=str(raw.get("id", "")),
            slug=str(raw.get("slug", "")),
            title=str(raw.get("title", "")),
            description=str(raw.get("description", "")),
            project_type=str(raw.get("project_type", "")),
            loaders=tuple(str(v) for v in (raw.get("loaders") or ())),
            game_versions=tuple(str(v) for v in (raw.get("game_versions") or ())),
            downloads=int(raw.get("downloads", 0) or 0),
            version_count=len(versions),
        )


@dataclass(slots=True)
class Detected:
    """从 jar 元数据 / 文件名里"探测"到的信息；mc_versions 仅作提示。"""

    mc_versions: list[str] = field(default_factory=list)
    loaders: list[str] = field(default_factory=list)
    mod_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """序列化。"""
        return {"mc_versions": list(self.mc_versions), "loaders": list(self.loaders),
                "mod_version": self.mod_version}

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "Detected":
        """从字典还原。"""
        raw = raw or {}
        return cls(
            mc_versions=[str(v) for v in (raw.get("mc_versions") or ())],
            loaders=[str(v) for v in (raw.get("loaders") or ())],
            mod_version=raw.get("mod_version"),
        )


@dataclass(slots=True)
class ModEntry:
    """模组清单里的一条记录。"""

    key: str
    display_name: str
    cn_name: str | None = None
    mod_id: str | None = None
    file_name: str | None = None
    sha1: str | None = None
    aliases: list[str] = field(default_factory=list)
    sources: dict[str, str | None] = field(default_factory=dict)
    detected: Detected = field(default_factory=Detected)
    match_status: MatchStatus = MatchStatus.UNMATCHED
    source_kind: SourceKind | None = None
    current_version: str | None = None
    notes: str = ""
    added_at: str = ""
    updated_at: str = ""

    @property
    def best_name(self) -> str:
        """界面上优先显示的名字：中文名 > 展示名 > modid > key。"""
        return self.cn_name or self.display_name or self.mod_id or self.key

    def search_candidates(self) -> list[str]:
        """搜索用的候选名，按"最可能"排序并去重。

        顺序：mod_id -> display_name（即 jar 内展示名）-> 各来源文件名解析出的候选 -> key。
        纯中文名不进候选（对 Modrinth 搜索没有意义）。
        """
        from modcheck.core.filename import parse_jar_filename  # 延迟 import，避免循环

        out: list[str] = []

        def push(value: str | None) -> None:
            text = (value or "").strip()
            if text and text not in out and not _is_cjk_only(text):
                out.append(text)

        push(self.mod_id)
        push(self.display_name)
        for name in [self.file_name, *self.aliases]:
            if not name:
                continue
            parsed = parse_jar_filename(name)
            for candidate in parsed.name_candidates:
                push(candidate)
            push(parsed.name)
        push(self.key)
        return out

    def to_dict(self) -> dict[str, Any]:
        """序列化（枚举写字符串值）。"""
        return {
            "key": self.key,
            "display_name": self.display_name,
            "cn_name": self.cn_name,
            "mod_id": self.mod_id,
            "file_name": self.file_name,
            "sha1": self.sha1,
            "aliases": list(self.aliases),
            "sources": dict(self.sources),
            "detected": self.detected.to_dict(),
            "match_status": self.match_status.value,
            "source_kind": self.source_kind.value if self.source_kind else None,
            "current_version": self.current_version,
            "notes": self.notes,
            "added_at": self.added_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ModEntry":
        """从字典还原；未知字段忽略，非法枚举值退化为默认值。"""
        kind = raw.get("source_kind")
        try:
            source_kind = SourceKind(kind) if kind else None
        except ValueError:
            source_kind = None
        try:
            match_status = MatchStatus(str(raw.get("match_status", MatchStatus.UNMATCHED.value)))
        except ValueError:
            match_status = MatchStatus.UNMATCHED
        key = str(raw.get("key") or raw.get("mod_id") or raw.get("display_name") or "")
        return cls(
            key=key,
            display_name=str(raw.get("display_name") or key),
            cn_name=raw.get("cn_name"),
            mod_id=raw.get("mod_id"),
            file_name=raw.get("file_name"),
            sha1=raw.get("sha1"),
            aliases=[str(v) for v in (raw.get("aliases") or ())],
            sources={str(k): (None if v is None else str(v))
                     for k, v in dict(raw.get("sources") or {}).items()},
            detected=Detected.from_dict(raw.get("detected")),
            match_status=match_status,
            source_kind=source_kind,
            current_version=raw.get("current_version"),
            notes=str(raw.get("notes") or ""),
            added_at=str(raw.get("added_at") or ""),
            updated_at=str(raw.get("updated_at") or ""),
        )


@dataclass(slots=True)
class Profile:
    """一份模组清单。"""

    schema_version: int = 1
    name: str = ""
    description: str = ""
    created_at: str = ""
    updated_at: str = ""
    mods: list[ModEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """序列化。"""
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "mods": [m.to_dict() for m in self.mods],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Profile":
        """从字典还原。"""
        if "mods" not in raw:
            raise ConfigError(t("err.profile.schema", path=""))
        return cls(
            schema_version=int(raw.get("schema_version", 1) or 1),
            name=str(raw.get("name") or ""),
            description=str(raw.get("description") or ""),
            created_at=str(raw.get("created_at") or ""),
            updated_at=str(raw.get("updated_at") or ""),
            mods=[ModEntry.from_dict(m) for m in (raw.get("mods") or ())],
        )


def _is_cjk_only(text: str) -> bool:
    """判断字符串是否只由 CJK 字符与标点组成（这种名字不进搜索候选）。"""
    has_cjk = False
    for ch in text:
        if ch.isascii():
            if ch.isalnum():
                return False
            continue
        has_cjk = True
    return has_cjk


@dataclass(slots=True)
class Settings:
    """程序设置（settings.json 的模型）。"""

    schema_version: int = 1
    default_mc_version: str | None = None
    default_loader: Loader = Loader.FABRIC
    color: str = "auto"
    proxy: str | None = None
    concurrency: int = 6
    timeout_seconds: float = 20.0
    retries: int = 3
    cache_ttl_hours: dict[str, float] = field(
        default_factory=lambda: {"mojang": 24.0, "api": 6.0})
    providers: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {
            "modrinth": {"enabled": True},
            "curseforge": {"enabled": False, "api_key": None},
        })

    def to_dict(self) -> dict[str, Any]:
        """序列化（加载器写字符串值）。"""
        return {
            "schema_version": self.schema_version,
            "default_mc_version": self.default_mc_version,
            "default_loader": self.default_loader.value,
            "color": self.color,
            "proxy": self.proxy,
            "concurrency": int(self.concurrency),
            "timeout_seconds": float(self.timeout_seconds),
            "retries": int(self.retries),
            "cache_ttl_hours": {str(k): float(v) for k, v in self.cache_ttl_hours.items()},
            "providers": {str(k): dict(v) for k, v in self.providers.items()},
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Settings":
        """从字典还原；坏的字段用默认值，绝不抛异常。"""
        default = cls()
        try:
            loader = Loader.parse(str(raw.get("default_loader", default.default_loader.value)))
        except ConfigError:
            loader = Loader.FABRIC
        ttl_raw = dict(raw.get("cache_ttl_hours") or {})
        ttl = dict(default.cache_ttl_hours)
        for key, value in ttl_raw.items():
            try:
                ttl[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
        providers = default.providers
        incoming = raw.get("providers")
        if isinstance(incoming, dict) and incoming:
            providers = {}
            for name, conf in incoming.items():
                providers[str(name)] = dict(conf) if isinstance(conf, dict) else {}
            for name, conf in default.providers.items():
                providers.setdefault(name, dict(conf))
        def _num(value: Any, fallback: float) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return fallback

        color = str(raw.get("color") or "auto")
        if color not in ("auto", "always", "never"):
            color = "auto"
        return cls(
            schema_version=int(_num(raw.get("schema_version"), 1)),
            default_mc_version=raw.get("default_mc_version") or None,
            default_loader=loader,
            color=color,
            proxy=raw.get("proxy") or None,
            concurrency=int(_num(raw.get("concurrency"), default.concurrency)),
            timeout_seconds=_num(raw.get("timeout_seconds"), default.timeout_seconds),
            retries=int(_num(raw.get("retries"), default.retries)),
            cache_ttl_hours=ttl,
            providers=providers,
        )


__all__ = [
    "Loader", "Status", "ReasonCode", "MatchStatus", "SourceKind",
    "FileInfo", "VersionInfo", "ProjectHit", "ProjectInfo",
    "Detected", "ModEntry", "Profile", "Settings",
]
