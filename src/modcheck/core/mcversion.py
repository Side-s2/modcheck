"""MC 版本号的识别、比较与校验。

只做"版本号长什么样、谁更大"的纯计算；**不参与兼容性判定**
（判定只做字符串精确包含，见 core/checker.py）。

注意：Minecraft 已改用年份制版本号（26.3），历史版本仍是 1.21.x，
所以绝不能假设 1.x 形式，也绝不能按字符串比较大小（"1.9" > "1.21" 是错的）。
"""
from __future__ import annotations

import re
from typing import Collection, Final, Iterable

from modcheck.errors import ConfigError
from modcheck.i18n import t

#: 正式版样式：26.3 / 26.1.2 / 1.21.4
RELEASE_RE: Final[re.Pattern[str]] = re.compile(r"^\d+\.\d+(\.\d+)?$")
#: 快照样式：24w14a / 26.4-snapshot-2 / 1.21-pre1 / 1.21-rc1
SNAPSHOT_RE: Final[re.Pattern[str]] = re.compile(
    r"^(\d{2}w\d{2}[a-z]|\d+\.\d+[-.](snapshot|pre|rc)[-.]?\d*)$", re.IGNORECASE)
#: 年份制的起点：大于等于这个主版本号就当成年份制
_YEAR_BASED_MAJOR: Final[int] = 20


def is_release_like(value: str) -> bool:
    """是否是正式版样式的版本号。"""
    return bool(RELEASE_RE.match((value or "").strip()))


def is_snapshot_like(value: str) -> bool:
    """是否是快照样式的版本号。"""
    return bool(SNAPSHOT_RE.match((value or "").strip()))


def version_key(value: str) -> tuple[int, int, int]:
    """把版本号转成可比较的元组；非法返回 (-1, -1, -1)。"""
    text = (value or "").strip()
    if not is_release_like(text):
        return (-1, -1, -1)
    parts = [int(p) for p in text.split(".")]
    while len(parts) < 3:
        parts.append(0)
    return (parts[0], parts[1], parts[2])


def compare(a: str, b: str) -> int:
    """比较两个版本号：a>b 返回 1，a<b 返回 -1，相等返回 0。"""
    ka, kb = version_key(a), version_key(b)
    return (ka > kb) - (ka < kb)


def max_release(versions: Iterable[str]) -> str | None:
    """从一堆版本号里挑出最大的正式版号（忽略快照与非法值）。"""
    best: str | None = None
    best_key = (-1, -1, -1)
    for item in versions:
        text = (item or "").strip()
        key = version_key(text)
        if key == (-1, -1, -1):
            continue
        if best is None or key > best_key:
            best, best_key = text, key
    return best


def sort_releases(versions: Iterable[str]) -> list[str]:
    """把正式版号按从新到旧排序（忽略快照与非法值，结果去重）。"""
    seen: dict[str, tuple[int, int, int]] = {}
    for item in versions:
        text = (item or "").strip()
        key = version_key(text)
        if key == (-1, -1, -1) or text in seen:
            continue
        seen[text] = key
    return sorted(seen, key=lambda v: seen[v], reverse=True)


def validate_target_version(value: str, known: Collection[str] | None) -> None:
    """校验用户输入的目标游戏版本。

    参数：
        value: 用户输入的版本号。
        known: 官方正式版清单；为空/None 时跳过"是否存在"的检查（例如没联网）。

    抛出：
        ConfigError: 格式非法、是快照版、或不在官方清单里。
    """
    text = (value or "").strip()
    if not is_release_like(text):
        if is_snapshot_like(text):
            raise ConfigError(t("err.mc.snapshot", value=value))
        raise ConfigError(t("err.mc.invalid", value=value))
    if known:
        if text not in set(known):
            recent = "、".join(sort_releases(known)[:3])
            raise ConfigError(t("err.mc.unknown", value=text, recent=recent))


__all__ = [
    "RELEASE_RE", "SNAPSHOT_RE", "is_release_like", "is_snapshot_like",
    "version_key", "compare", "max_release", "sort_releases", "validate_target_version",
]
