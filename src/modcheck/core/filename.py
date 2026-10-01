"""jar 文件名解析（**低置信兜底**，见基线 §11.2）。

实测结论：14 个真实常见文件名里朴素解析只有 3 个正确。所以本模块的产物
  ① 永远带 confidence="low"；
  ② **绝对不允许**参与兼容性判定，也不允许用它的 MC 版本做任何结论；
  ③ 唯一用途：用户只有一份文件名清单（没有 jar）时，尽力给出候选名去搜索。

解析顺序：去后缀 → 取全部前导 [中文名] → 按 + 切分判定 MC/模组版本 →
剥离位置 0 或 -1 的加载器 token → 用官方版本清单做锚点找 MC 版本 →
尾部版本样式并入模组版本 → 剩下的 join 成候选名。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Collection, Final

from modcheck.core.mcversion import is_release_like

#: 归档后缀，长的必须在前（.jar.disabled 优先于 .jar）
ARCHIVE_SUFFIXES: Final[tuple[str, ...]] = (".jar.disabled", ".jar.old", ".jar.bak", ".zip", ".jar")
#: 表示"已禁用/已备份"的后缀
DISABLED_TOKENS: Final[tuple[str, ...]] = (".disabled", ".old", ".bak", ".off")
#: 可能出现在文件名里的加载器 token
LOADER_TOKENS: Final[tuple[str, ...]] = ("fabric", "forge", "neoforge", "quilt", "paper")

_VERSION_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^\d+(\.\d+)*([-+].*)?$")
# 通道词必须自成一段，否则 "servercore" 里的 "rc" 会被误判成版本的一部分
_CHANNEL_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^(alpha|beta|rc|pre)([-.]?\d+)*$", re.IGNORECASE)
_MC_PREFIX_RE: Final[re.Pattern[str]] = re.compile(r"^(?:mc|v)(?=\d)", re.IGNORECASE)
#: 启发式里"年份制"的起点（主版本 >= 20 视为年份制版本号）
_YEAR_BASED_MAJOR: Final[int] = 20


@dataclass(frozen=True, slots=True)
class ParsedName:
    """文件名解析结果（永远是低置信）。"""

    raw: str
    cn_name: str | None
    extra_cn_names: tuple[str, ...]
    loader: str | None
    name: str | None
    name_candidates: tuple[str, ...]
    mc_version: str | None
    mod_version: str | None
    confidence: str = "low"


def strip_archive_suffix(filename: str) -> str:
    """去掉归档后缀（.jar.disabled 优先于 .jar）。"""
    text = (filename or "").strip()
    low = text.lower()
    for suffix in ARCHIVE_SUFFIXES:
        if low.endswith(suffix):
            return text[: len(text) - len(suffix)]
    return text


def split_cn_prefix(stem: str) -> tuple[list[str], str]:
    """取出全部前导 [中文名]，返回 (中文名列表, 剩余部分)。"""
    names: list[str] = []
    rest = (stem or "").strip()
    while rest.startswith("["):
        end = rest.find("]")
        if end < 0:
            break
        inner = rest[1:end].strip()
        if inner:
            names.append(inner)
        rest = rest[end + 1:].strip()
    return names, rest


def looks_like_mc_version(tok: str, known: Collection[str] | None = None) -> bool:
    """判断一个 token 是否像 Minecraft 版本号。

    有官方清单时**只认清单**（最可靠）；没有清单时用启发式：
    主版本 >= 20（年份制），或 1.7~1.21 且补丁号不超过 25
    （避免把 1.10.53 这种模组版本误认成 MC 版本）。
    """
    text = (tok or "").strip()
    if not text:
        return False
    if known:
        return text in set(known)
    if not is_release_like(text):
        return False
    parts = [int(p) for p in text.split(".")]
    major = parts[0]
    minor = parts[1] if len(parts) > 1 else 0
    patch = parts[2] if len(parts) > 2 else 0
    if major >= _YEAR_BASED_MAJOR:
        return True
    if major == 1 and 7 <= minor <= 21:
        return len(parts) < 3 or patch <= 25
    return False


def is_archive_like(name: str) -> bool:
    """是否像可扫描的归档文件。"""
    low = (name or "").strip().lower()
    return any(low.endswith(suffix) for suffix in ARCHIVE_SUFFIXES)


def is_disabled_like(name: str) -> bool:
    """是否是"已禁用/已备份"的文件。"""
    low = (name or "").strip().lower()
    return any(low.endswith(token) for token in DISABLED_TOKENS)


def _versionish(token: str) -> bool:
    """是否是"纯版本样式"或纯测试通道词的 token。"""
    return bool(_VERSION_TOKEN_RE.match(token)) or bool(_CHANNEL_TOKEN_RE.match(token))


def parse_jar_filename(filename: str, *,
                       known_mc_versions: Collection[str] | None = None) -> ParsedName:
    """解析一个 jar 文件名（低置信兜底）。

    参数：
        filename: 文件名（可带路径也可以只给名字）。
        known_mc_versions: 官方正式版清单，用于"锚点"式识别 MC 版本。

    返回：
        ParsedName；所有结果的 confidence 恒为 "low"。
    """
    raw = filename or ""
    stem = strip_archive_suffix(raw)
    cn_names, rest = split_cn_prefix(stem)
    cn_name = cn_names[0] if cn_names else None
    extra_cn_names = tuple(cn_names[1:])

    mc_version: str | None = None
    mod_version: str | None = None

    if "+" in rest:
        lhs, _, rhs = rest.partition("+")
        tokens = [tok for tok in lhs.split("-") if tok]
        rhs_text = rhs.strip()
        rhs_core = _MC_PREFIX_RE.sub("", rhs_text)
        if tokens and looks_like_mc_version(tokens[-1], known_mc_versions):
            mc_version = tokens.pop()
            mod_version = rhs_text or None
        elif rhs_text and looks_like_mc_version(rhs_core, known_mc_versions):
            mc_version = rhs_core
            mod_version = tokens.pop() if tokens else None
        else:
            mod_version = rhs_text or None
    else:
        tokens = [tok for tok in rest.split("-") if tok]

    original_tokens = list(tokens)
    # 只记录"被判成版本号而被移除"的 token；加载器 token 不算，
    # 因为 name_candidates 里要保留"不剥离加载器"的完整形态（如 fabric-api）。
    removed_versions: list[str] = []
    loader: str | None = None

    # 不动点循环：剥加载器 -> 找 MC 锚点 -> 合并尾部版本，直到没有变化
    changed = True
    while changed:
        changed = False
        if tokens:
            if tokens[0].lower() in LOADER_TOKENS:
                loader = loader or tokens[0].lower()
                tokens.pop(0)
                changed = True
            elif tokens[-1].lower() in LOADER_TOKENS:
                loader = loader or tokens[-1].lower()
                tokens.pop()
                changed = True
        if mc_version is None:
            for index, token in enumerate(tokens):
                candidate = _MC_PREFIX_RE.sub("", token)
                if looks_like_mc_version(candidate, known_mc_versions):
                    mc_version = candidate
                    removed_versions.append(tokens.pop(index))
                    changed = True
                    break
        if tokens and _versionish(tokens[-1]) and tokens[-1] not in removed_versions:
            tail = tokens.pop()
            removed_versions.append(tail)
            changed = True
            if mod_version and tail not in mod_version:
                mod_version = tail + "+" + mod_version
            else:
                mod_version = mod_version or tail

    name = "-".join(tokens) if tokens else None
    full = "-".join(tok for tok in original_tokens if tok not in removed_versions)
    candidates: list[str] = []
    for item in (name, full):
        if item and item not in candidates:
            candidates.append(item)

    return ParsedName(
        raw=raw,
        cn_name=cn_name,
        extra_cn_names=extra_cn_names,
        loader=loader,
        name=name,
        name_candidates=tuple(candidates),
        mc_version=mc_version,
        mod_version=mod_version,
    )


__all__ = [
    "ARCHIVE_SUFFIXES", "DISABLED_TOKENS", "LOADER_TOKENS", "ParsedName",
    "strip_archive_suffix", "split_cn_prefix", "looks_like_mc_version",
    "parse_jar_filename", "is_archive_like", "is_disabled_like",
]
