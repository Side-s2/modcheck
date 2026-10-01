"""T-08 匹配规则测试（slug 优先，绝不猜）。"""
from __future__ import annotations

from conftest import load_fixture

from modcheck.core.matching import (MatchResult, format_downloads, match_exact, normalize,
                                    rank_candidates)
from modcheck.core.models import ProjectHit


def _hits(name: str) -> list[ProjectHit]:
    data = load_fixture(name)
    return [ProjectHit.from_api(item) for item in data["hits"]]


def test_normalize() -> None:
    """normalize：转小写并删掉 - _ 空格 ."""
    assert normalize("ferrite-core") == normalize("ferritecore")
    assert normalize("Ferrite Core") == "ferritecore"
    assert normalize("Carpet TIS Addition") != normalize("carpet")
    assert normalize("a.b_c-d e") == "abcde"


def test_search_carpet_exact_slug() -> None:
    """真实 search_carpet.json（8 条）里认 carpet。"""
    result = match_exact(_hits("search_carpet.json"), ["carpet"])
    assert result.hit is not None
    assert result.hit.slug == "carpet"
    assert result.how == "slug"
    assert result.ambiguous is False


def test_search_carpet_other_candidates() -> None:
    """候选名按 normalize 完全同名认定。"""
    assert match_exact(_hits("search_carpet.json"), ["Carpet Fixes"]).hit is not None
    assert match_exact(_hits("search_carpet.json"), ["carpet-tis-addition"]).hit is not None


def test_carpet_tis_addition_is_exact_match() -> None:
    """与任务书 §4.2 用例 20 的出入（已在交付总结里记录）：

    真实数据里 Modrinth 确实存在 title="Carpet TIS Addition" 的项目，
    按基线 §8 第 3 步的规则（title 恰好命中 1 个）应当自动认定，
    而不是判成 ambiguous —— 判成 ambiguous 反而会让用户白忙。
    """
    result = match_exact(_hits("search_carpet.json"), ["Carpet TIS Addition"])
    assert result.hit is not None
    assert result.hit.slug == "carpet-tis-addition"


def test_ambiguous_means_do_not_guess() -> None:
    """同一候选名命中两条 -> 不自动认定（ambiguous=True），绝不猜。"""
    hits = [
        ProjectHit("P1", "carpet-extra", "Carpet Extra", 10, "d", "modrinth"),
        ProjectHit("P2", "carpet.extra", "Carpet Extra", 20, "d", "modrinth"),
    ]
    result = match_exact(hits, ["Carpet Extra"])
    assert isinstance(result, MatchResult)
    assert result.hit is None
    assert result.ambiguous is True


def test_no_hits_at_all() -> None:
    """搜索没有结果 -> hit=None 且 not ambiguous。"""
    result = match_exact([], ["whatever"])
    assert result.hit is None
    assert result.ambiguous is False
    assert result.how == "none"


def test_slug_wins_over_title_distractor() -> None:
    """实测场景：搜 chunky 时 title 还命中 newbiichunkymod，仍以 slug 命中为准。"""
    hits = _hits("search_chunky.json")
    assert hits[0].slug != "chunky"  # 干扰项排在前面，证明不是"取第一条"
    result = match_exact(hits, ["chunky"])
    assert result.hit is not None
    assert result.hit.slug == "chunky"
    assert result.how == "slug"


def test_candidates_are_tried_in_order() -> None:
    """前一个候选没有完全同名时继续尝试后面的候选。"""
    hits = _hits("search_carpet.json")
    result = match_exact(hits, ["some-random-name", "carpet"])
    assert result.hit is not None
    assert result.hit.slug == "carpet"


def test_rank_candidates_puts_exact_first() -> None:
    """精确同名优先，其次前缀匹配，最后按下载量降序。"""
    hits = _hits("search_carpet.json")
    ranked = rank_candidates(hits, ["carpet"])
    assert ranked[0].slug == "carpet"
    assert ranked[1].downloads >= 0


def test_format_downloads() -> None:
    """下载量加千分位。"""
    assert format_downloads(11016662) == "11,016,662"
    assert format_downloads(0) == "0"
