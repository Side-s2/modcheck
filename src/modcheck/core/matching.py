"""模组名 -> 平台项目的匹配（决策 A4 的纯逻辑实现）。

规则（基线 §8 第 3 步，**slug 唯一命中优先于 title 命中**）：
    对每个候选名 N：
      ① normalize(slug) == normalize(N) 的命中恰好 1 个 -> 认定（how="slug"）；
      ② 否则 normalize(title) == normalize(N) 的命中恰好 1 个 -> 认定（how="title"）；
      ③ 否则换下一个候选；全都不行 -> hit=None。
**绝不**做相似度打分自动认定（PRD §1.4 的 C3 反例：那会把服务器搞崩）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Sequence

from modcheck.core.models import ModEntry, ProjectHit

_STRIP_RE: Final[re.Pattern[str]] = re.compile(r"[-_ .\s]+")


def normalize(text: str) -> str:
    """规范化比较键：转小写并删掉 - _ 空格 .（仅用于"完全同名"判断）。"""
    return _STRIP_RE.sub("", (text or "").lower())


def candidate_names(entry: ModEntry) -> list[str]:
    """搜索候选名（mod_id -> 展示名 -> 文件名候选 -> key，去重保序）。"""
    return entry.search_candidates()


@dataclass(frozen=True, slots=True)
class MatchResult:
    """精确同名匹配的结果。"""

    hit: ProjectHit | None
    how: str
    ambiguous: bool


def match_exact(hits: Sequence[ProjectHit], candidates: Sequence[str]) -> MatchResult:
    """按 PRD §8 的规则做"完全同名"匹配。

    参数：
        hits: 搜索返回的候选（顺序即搜索相关性顺序）。
        candidates: 依次尝试的候选名。
    返回：
        MatchResult；没找到时 hit=None，ambiguous 表示"有候选但不唯一"。
    """
    for candidate in candidates:
        key = normalize(candidate)
        if not key:
            continue
        slug_hits = [h for h in hits if normalize(h.slug) == key]
        if len(slug_hits) == 1:
            return MatchResult(hit=slug_hits[0], how="slug", ambiguous=False)
        title_hits = [h for h in hits if normalize(h.title) == key]
        if len(title_hits) == 1:
            return MatchResult(hit=title_hits[0], how="title", ambiguous=False)
    return MatchResult(hit=None, how="none", ambiguous=len(hits) > 0)


def rank_candidates(hits: Sequence[ProjectHit], candidates: Sequence[str]) -> list[ProjectHit]:
    """给交互式候选列表排序：完全同名 -> 前缀匹配 -> 下载量降序。"""
    keys = [normalize(c) for c in candidates if normalize(c)]

    def score(hit: ProjectHit) -> tuple[int, int]:
        slug, title = normalize(hit.slug), normalize(hit.title)
        rank = 2
        for key in keys:
            if key in (slug, title):
                rank = 0
                break
            if slug.startswith(key) or title.startswith(key):
                rank = min(rank, 1)
        return (rank, -int(hit.downloads))

    return sorted(hits, key=score)


def format_downloads(count: int) -> str:
    """下载量加千分位（11016662 -> 11,016,662）。"""
    return f"{int(count):,}"


__all__ = ["normalize", "candidate_names", "MatchResult", "match_exact",
           "rank_candidates", "format_downloads"]
