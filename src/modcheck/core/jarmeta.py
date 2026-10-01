"""读取 jar 内部元数据（**第一优先识别手段**，见基线 §11.4）。

支持的成员（按优先级）：
    fabric.mod.json -> quilt.mod.json -> META-INF/neoforge.mods.toml
    -> META-INF/mods.toml -> META-INF/MANIFEST.MF

硬性要求：
  * **永不抛异常**：损坏的 zip、加密条目、超大条目都只写进 JarMeta.error；
  * 只读需要的成员，单个成员上限 MAX_MEMBER_BYTES，绝不整包解压；
  * 实测：Fabric 模组不一定声明 depends.minecraft（jei 就是 None），
    所以 mc_hint 只作提示，**绝不参与判定**。
"""
from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from modcheck.core.mcversion import is_release_like
from modcheck.i18n import t

#: 单个元数据成员的读取上限（防超大 jar 把内存吃光）
MAX_MEMBER_BYTES: Final[int] = 2 * 1024 * 1024
#: 成员查找优先级（高 -> 低）
MEMBER_PRIORITY: Final[tuple[str, ...]] = (
    "fabric.mod.json",
    "quilt.mod.json",
    "META-INF/neoforge.mods.toml",
    "META-INF/mods.toml",
    "META-INF/MANIFEST.MF",
)

_COMPARE_RE: Final[re.Pattern[str]] = re.compile(r"^[><=~^!\s]+")


@dataclass(frozen=True, slots=True)
class JarMeta:
    """一个 jar 的元数据读取结果。"""

    path: Path
    mod_id: str | None = None
    name: str | None = None
    version: str | None = None
    loader_hint: str | None = None
    mc_hint: str | None = None
    depends: dict[str, list[str]] = field(default_factory=dict)
    source_member: str | None = None
    error: str | None = None

    @property
    def has_meta(self) -> bool:
        """是否读到了可用于识别的元数据。"""
        return self.source_member is not None and self.error is None


def _as_text(value: Any) -> str | None:
    """把可能是 str / dict（多语言）/ 数字的字段统一成字符串。"""
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("en_us", "zh_cn", "en_US"):
            if key in value:
                return str(value[key])
        for item in value.values():
            return str(item)
        return None
    text = str(value).strip()
    return text or None


def _normalize_depends(raw: Any) -> dict[str, list[str]]:
    """把 depends 统一成 {modid: [版本范围, ...]}。"""
    out: dict[str, list[str]] = {}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        items: list[str] = []
        if isinstance(value, str):
            items = value.split()
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str):
                    items.extend(item.split())
                elif item is not None:
                    items.append(str(item))
        elif value is not None:
            items = [str(value)]
        out[str(key)] = [item for item in items if item]
    return out


def left_bound(range_text: str | None) -> str | None:
    """从版本范围里取左界（如 "[1.20.1,1.21)" -> "1.20.1"）。

    解析不出来时返回 None —— **绝不猜**（Forge 的 versionRange 常带 [ ) 混写）。
    """
    text = (range_text or "").strip()
    if not text or text == "*":
        return None
    if text[0] in "[(":
        text = text[1:]
    for sep in (",", "]", ")"):
        index = text.find(sep)
        if index >= 0:
            text = text[:index]
    text = _COMPARE_RE.sub("", text).strip()
    return text or None


def parse_fabric_json(raw: bytes) -> tuple[str | None, str | None, str | None,
                                              dict[str, list[str]], str | None]:
    """解析 fabric.mod.json / quilt.mod.json。

    返回：
        (mod_id, name, version, depends, error)
    """
    try:
        data = json.loads(raw.decode("utf-8", errors="replace") or "{}")
    except (ValueError, UnicodeDecodeError) as exc:
        return None, None, None, {}, t("jar.error.read", detail=type(exc).__name__)
    if not isinstance(data, dict):
        return None, None, None, {}, t("jar.error.no_meta")
    return (_as_text(data.get("id")), _as_text(data.get("name")), _as_text(data.get("version")),
            _normalize_depends(data.get("depends")), None)


def parse_mods_toml(raw: bytes) -> tuple[str | None, str | None, str | None,
                                          dict[str, list[str]], str | None]:
    """解析 META-INF/mods.toml 与 META-INF/neoforge.mods.toml。

    返回：
        (mod_id, name, version, depends, error)
    """
    try:
        import tomllib

        data = tomllib.loads(raw.decode("utf-8", errors="replace"))
    except Exception as exc:  # tomllib 的异常类型随版本变化，这里统一兜底
        return None, None, None, {}, t("jar.error.read", detail=type(exc).__name__)
    mods = data.get("mods")
    if not isinstance(mods, list) or not mods or not isinstance(mods[0], dict):
        return None, None, None, {}, t("jar.error.no_meta")
    first = mods[0]
    depends: dict[str, list[str]] = {}
    raw_deps = data.get("dependencies")
    if isinstance(raw_deps, dict):
        for entries in raw_deps.values():
            if not isinstance(entries, list):
                continue
            for item in entries:
                if not isinstance(item, dict):
                    continue
                mod_id = _as_text(item.get("modId"))
                if not mod_id:
                    continue
                range_text = _as_text(item.get("versionRange")) or ""
                depends.setdefault(mod_id, []).append(range_text)
    return (_as_text(first.get("modId")), _as_text(first.get("displayName")),
            _as_text(first.get("version")), depends, None)


def parse_manifest(raw: bytes) -> tuple[str | None, str | None, str | None,
                                        dict[str, list[str]], str | None]:
    """解析 META-INF/MANIFEST.MF（最后的兜底；拿不到 modid）。"""
    text = raw.decode("utf-8", errors="replace")
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip().lower()] = value.strip()
    name = fields.get("implementation-title") or fields.get("specification-title")
    version = fields.get("implementation-version") or fields.get("specification-version")
    if not name and not version:
        return None, None, None, {}, t("jar.error.no_meta")
    return None, name, version, {}, None


def _mc_hint_from_depends(depends: dict[str, list[str]]) -> str | None:
    """从 depends.minecraft 的左界推出 MC 版本提示（仅提示）。"""
    for value in depends.get("minecraft", []):
        bound = left_bound(value)
        if bound and is_release_like(bound):
            return bound
    return None


def read_jar_meta(path: Path) -> JarMeta:
    """读取 jar 内部元数据；任何异常都吞掉并写进 error，永不抛出。"""
    target = Path(path)
    try:
        if not target.is_file():
            return JarMeta(path=target, error=t("jar.error.not_found"))
        with zipfile.ZipFile(target) as zf:
            names = {name.lower(): name for name in zf.namelist()}
            for member in MEMBER_PRIORITY:
                real = names.get(member.lower())
                if real is None:
                    continue
                try:
                    info = zf.getinfo(real)
                    if info.file_size > MAX_MEMBER_BYTES:
                        return JarMeta(path=target, error=t("jar.error.too_large", limit=MAX_MEMBER_BYTES))
                    raw = zf.read(real)
                except (KeyError, RuntimeError, zipfile.BadZipFile, OSError) as exc:
                    return JarMeta(path=target, error=t("jar.error.read", detail=type(exc).__name__))
                if member.endswith(".json"):
                    mod_id, name, version, depends, error = parse_fabric_json(raw)
                elif member.endswith(".toml"):
                    mod_id, name, version, depends, error = parse_mods_toml(raw)
                else:
                    mod_id, name, version, depends, error = parse_manifest(raw)
                if error is not None and member != MEMBER_PRIORITY[-1]:
                    continue
                loader = None
                if member in ("fabric.mod.json", "quilt.mod.json"):
                    loader = "fabric" if member == "fabric.mod.json" else "quilt"
                elif member.endswith("neoforge.mods.toml"):
                    loader = "neoforge"
                elif member.endswith("mods.toml"):
                    loader = "forge"
                return JarMeta(path=target, mod_id=mod_id, name=name, version=version,
                               loader_hint=loader, mc_hint=_mc_hint_from_depends(depends),
                               depends=depends, source_member=member, error=None)
            return JarMeta(path=target, error=t("jar.error.no_meta"))
    except zipfile.BadZipFile:
        return JarMeta(path=target, error=t("jar.error.broken"))
    except (OSError, ValueError, EOFError) as exc:
        return JarMeta(path=target, error=t("jar.error.read", detail=type(exc).__name__))
    except Exception as exc:  # 兜底：读 jar 绝不允许把整个扫描打断
        return JarMeta(path=target, error=t("jar.error.read", detail=type(exc).__name__))


__all__ = [
    "MAX_MEMBER_BYTES", "MEMBER_PRIORITY", "JarMeta", "read_jar_meta",
    "parse_fabric_json", "parse_mods_toml", "parse_manifest", "left_bound",
]
