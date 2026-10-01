"""兼容性判定的编排：清单 × 目标版本 × 加载器 -> 报告（BRIEF §5 的 checker 职责）。

这里的每一条"省请求"的写法都对应一条实测教训：
  * **B 只在 A[0] 不支持目标版本时才请求** —— A[0] 支持就是 🟢，问 B 是浪费；
  * **A2 只在 A 为空时请求** —— 用来区分"完全没有该加载器"和"只有测试版"；
  * **get_project 只在 A 与 A2 都为空时请求** —— version_count 只服务 NO_FILES 分支，
    正常模组根本用不到它（否则每个模组白花一个请求）。
最坏情况 3 个请求，正常模组 1~2 个。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Final, Sequence

from modcheck.core.checker import Classification, classify, for_reason
from modcheck.core.matching import candidate_names, match_exact
from modcheck.core.models import (Loader, MatchStatus, ModEntry, ProjectHit, ReasonCode,
                                  Status)
from modcheck.core.report import ReportItem
from modcheck.errors import ProviderError
from modcheck.i18n import t


class _ProviderLike:
    """仅用于类型提示的占位（真实对象由调用方注入 BaseProvider）。"""


def _blank_item(entry: ModEntry, result: Classification, *, current: str | None = None,
                message: str = "") -> ReportItem:
    """把判定结果包成报告条目。"""
    return ReportItem(
        mod=entry, status=result.status, reason=result.reason,
        reason_key=result.reason_key, hint_key=result.hint_key,
        latest_for_loader=result.latest_for_loader,
        latest_compat=result.latest_compat,
        latest_any=result.latest_any,
        max_supported_mc=result.max_supported_mc,
        available_loaders=result.available_loaders,
        current_version=current if current is not None else entry.current_version,
        provider_message=message,
    )


#: 显式 --resolve 时每个模组最多试几个候选名（防止"全是猜的"清单把预算打穿）
MAX_RESOLVE_CANDIDATES: Final[int] = 2


def _search_project(entry: ModEntry, provider, *, limit: int = 10,
                    max_candidates: int | None = None) -> tuple[str | None, str | None]:
    """按候选名做精确同名搜索，返回 (slug, 错误信息)。"""
    names = candidate_names(entry)
    if max_candidates is not None:
        names = names[:max_candidates]
    if not names:
        return None, ""
    for name in names:
        hits: Sequence[ProjectHit] = provider.search(name, limit=limit)
        result = match_exact(hits, [name])
        if result.hit is not None:
            return result.hit.slug, ""
    return None, ""


def _search_hits(entry: ModEntry, provider, *, limit: int = 10) -> list[ProjectHit]:
    """取第一个候选名的搜索结果（供交互弹窗列候选）。"""
    names = candidate_names(entry)
    if not names:
        return []
    return list(provider.search(names[0], limit=limit))


def check_one(entry: ModEntry, provider, *, loader: Loader, mc_version: str,
              window: int = 25, prerelease: bool = False, resolve: bool = False,
              interactive_match: Callable[[ModEntry, Sequence[ProjectHit]], str | None] | None = None
              ) -> ReportItem:
    """检查单个模组并返回报告条目（**任何异常都降级为 ⚪，绝不冒泡**）。"""
    if entry.match_status is MatchStatus.IGNORED:
        return _blank_item(entry, for_reason(ReasonCode.IGNORED))

    slug = entry.sources.get("modrinth")
    try:
        if not slug:
            # 裁决 D34：默认路径**不发搜索请求**。
            # 理由：scan（含 --from-list）已经用完全相同的规则试过全部候选名，
            # check 再搜一遍结果必然相同，纯属浪费；而且会让"每模组 <= 3 请求"的
            # 预算变得不可控。确定性优先，绝不把猜测引进本该确定的流程。
            hits: list[ProjectHit] = []
            if interactive_match is not None:
                # 交互模式是唯一的人工兜底通道（决策 A4）：只在这里发搜索
                hits = _search_hits(entry, provider)
                slug = interactive_match(entry, hits)
                if entry.match_status is MatchStatus.IGNORED:
                    return _blank_item(entry, for_reason(ReasonCode.IGNORED))
                if slug:
                    entry.sources["modrinth"] = slug
                    entry.match_status = MatchStatus.MANUAL
            elif resolve:
                # 显式 --resolve 才搜，且每模组最多试 MAX_RESOLVE_CANDIDATES 个候选
                slug, _ = _search_project(entry, provider, max_candidates=MAX_RESOLVE_CANDIDATES)
                if slug:
                    entry.sources["modrinth"] = slug
                    entry.match_status = MatchStatus.EXACT
            if not slug:
                return _blank_item(entry, for_reason(ReasonCode.UNMATCHED))

        releases = list(provider.releases_for_loader(slug, loader, window=window,
                                                     prerelease=prerelease))
        any_loader: list = []
        version_count: int | None = None
        if not releases:
            any_loader = list(provider.any_for_loader(slug, loader, window=window))
            if not any_loader:
                info = provider.get_project(slug)
                if info is None and not entry.sha1:
                    return _blank_item(entry, for_reason(ReasonCode.NOT_FOUND))
                version_count = info.version_count if info is not None else None

        compat: list = []
        compat_any: list = []
        first = releases[0] if releases else None
        if first is not None and mc_version in first.game_versions \
                and loader.value in first.loaders and (prerelease or first.is_release):
            # 快路径：目标加载器的最新版本来就支持目标版本 -> 不需要请求 B
            compat = [first]
        elif releases:
            compat = list(provider.compat_releases(slug, mc_version, loader, window=window,
                                                   prerelease=prerelease))
            if not compat:
                compat_any = list(provider.compat_any(slug, mc_version, loader, window=window))

        result = classify(loader=loader, mc_version=mc_version,
                          releases_for_loader=releases, compat_releases=compat,
                          compat_any=compat_any, any_for_loader=any_loader,
                          prerelease=prerelease, version_count=version_count)
        if result.reason is ReasonCode.NO_LOADER:
            info = provider.get_project(slug)
            if info is not None:
                result = classify(loader=loader, mc_version=mc_version,
                                  releases_for_loader=releases, compat_releases=compat,
                                  compat_any=compat_any, any_for_loader=any_loader,
                                  prerelease=prerelease, version_count=version_count,
                                  available_loaders=info.loaders)
        return _blank_item(entry, result)
    except ProviderError as exc:
        return _blank_item(entry, for_reason(ReasonCode.ERROR), message=exc.message)
    except Exception as exc:  # 单个模组失败绝不能中断整体检查（S4）
        return _blank_item(entry, for_reason(ReasonCode.ERROR),
                           message=t("err.internal", detail=type(exc).__name__))


def check_all(entries: Sequence[ModEntry], provider, *, loader: Loader, mc_version: str,
              window: int = 25, prerelease: bool = False, jobs: int = 6, resolve: bool = False,
              on_done: Callable[[int, int, ModEntry, ReportItem], None] | None = None,
              should_stop: Callable[[], bool] | None = None,
              interactive_match=None) -> list[ReportItem]:
    """并发检查（默认 6 线程，硬上限 8）；结果顺序与输入顺序一致。"""
    if not entries:
        return []
    workers = max(1, min(int(jobs), 8))
    results: list[ReportItem | None] = [None] * len(entries)
    done = 0

    def work_one(entry: ModEntry) -> ReportItem:
        return check_one(entry, provider, loader=loader, mc_version=mc_version,
                         window=window, prerelease=prerelease, resolve=resolve,
                         interactive_match=interactive_match)

    if workers == 1 or len(entries) == 1:
        for entry in entries:
            if should_stop is not None and should_stop():
                break
            item = work_one(entry)
            results[done] = item
            done += 1
            if on_done is not None:
                on_done(done, len(entries), entry, item)
    else:
        # pool.map 按输入顺序产出结果，既并发又保持报告行序稳定
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for entry, item in zip(entries, pool.map(work_one, entries)):
                if should_stop is not None and should_stop():
                    break
                results[done] = item
                done += 1
                if on_done is not None:
                    on_done(done, len(entries), entry, item)
    return [item for item in results if item is not None]


__all__ = ["check_one", "check_all", "MAX_RESOLVE_CANDIDATES"]
