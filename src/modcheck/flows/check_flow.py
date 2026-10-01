"""check 流程：模组清单 × 目标版本 × 加载器 -> Report。

本模块是「流程」层：**不打印任何东西**，进度用回调、取消用探针，结论装在 Report 里返回。
CLI 只负责渲染 Report，未来的 GUI 直接把同一份 Report 填进表格。

两条容易踩的边界都在这里保住：
  * 中断（Ctrl+C / 交互里 q）-> 返回 interrupted 报告，绝不抛 traceback；
  * 数据源整体不可用 -> 由 source_unavailable() 判定（退出码 4 的判据）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Protocol, Sequence

from modcheck.core.checker_run import check_all
from modcheck.core.models import Loader, ModEntry, ProjectHit
from modcheck.core.report import Report, ReportItem
from modcheck.errors import ConfigError, UserCancelled
from modcheck.i18n import t
from modcheck.storage.profiles import list_profiles, load_profile, profile_path

if TYPE_CHECKING:  # 只为类型注解；运行时不引入具体数据源（依赖注入）
    from modcheck.providers.base import BaseProvider

#: 进度回调：(已完成, 总数, 当前模组名)
ProgressFn = Callable[[int, int, str], None]
#: 逐条回调（终端用它统计阻塞数；签名与 core.checker_run.check_all 的 on_done 一致）
ItemFn = Callable[[int, int, ModEntry, ReportItem], None]
#: 取消探针：返回 True 表示调用方要求停下
StopFn = Callable[[], bool]
#: 交互匹配回调（PRD §5.7）：返回选中的 slug，None 表示跳过
MatchFn = Callable[[ModEntry, Sequence[ProjectHit]], "str | None"]


class StatsSource(Protocol):
    """请求统计的来源；真实实现是 providers/http.py 的 HttpClient。

    只依赖三个只读属性 —— 不 import 具体类，测试里塞任何鸭子类型对象都能跑。
    """

    @property
    def stats(self) -> tuple[int, int]:
        """(真实请求次数, 缓存命中次数)。"""
        ...

    @property
    def successes(self) -> int:
        """成功取到数据的次数（含缓存命中）。"""
        ...

    @property
    def rate_limited(self) -> int:
        """收到过的 429 次数。"""
        ...


@dataclass(slots=True)
class ProfileEntries:
    """这次检查用的模组清单来源（load_profile_entries 的返回值）。"""

    entries: list[ModEntry]
    name: str
    #: 清单是否本来就在磁盘上（--mods-dir 的临时清单不写盘）
    saved: bool
    #: 目录来源（--mods-dir 时是那个目录，否则空串）
    source: str = ""
    #: 清单文件路径（临时清单为 None）
    path: Path | None = None


def load_profile_entries(*, profiles_dir: Path, profile: str | None = None,
                         file: str | Path | None = None, mods_dir: str | Path | None = None,
                         provider: "BaseProvider | None" = None,
                         on_progress: ProgressFn | None = None,
                         should_stop: StopFn | None = None) -> ProfileEntries:
    """决定这次检查用哪份模组清单。

    参数：
        profiles_dir: 清单目录（CLI 传 ctx.profiles_dir）。
        profile: --profile 的清单名。
        file: --file 的清单文件路径（优先于 profile）。
        mods_dir: --mods-dir 的临时清单目录（与 profile 互斥）。
        provider: 注入给扫描的数据源；None 表示只靠 jar 内信息识别。
        on_progress / should_stop: 只作用于 --mods-dir 那条扫描路径。

    返回：
        ProfileEntries（条目、清单名、是否已落盘、目录来源、清单文件路径）。

    抛出：
        ConfigError: 参数互斥、目录不存在、清单不存在。
    """
    if profile and mods_dir:
        raise ConfigError(t("err.profile.mutex"))
    if mods_dir:
        directory = Path(mods_dir)
        if not directory.is_dir():
            raise ConfigError(t("err.dir.not_found", path=directory))
        # 延迟 import：scan_flow 与 check_flow 是同级流程，放模块顶部也行，
        # 但这里只在这一条分支用到，延迟 import 让依赖关系一眼可见。
        from modcheck.flows.scan_flow import scan_dirs

        report = scan_dirs([directory], provider=provider, on_progress=on_progress,
                           should_stop=should_stop)
        return ProfileEntries(report.entries, directory.name, False, str(directory), None)
    path = Path(file) if file else None
    if path is None:
        if not profile:
            raise ConfigError(t("err.no_profile_selected"))
        path = profile_path(profiles_dir, profile)
        if not path.exists():
            available = "、".join(p.name for p in list_profiles(profiles_dir))
            raise ConfigError(t("err.profile.not_found", name=profile,
                                available=available or t("err.profile.none_available")))
    loaded = load_profile(path)
    return ProfileEntries(loaded.mods, loaded.name or path.stem, True, "", path)


@dataclass(slots=True)
class CheckStats:
    """一次检查的运行统计：**检查区间**内的请求/限流增量。

    必须是增量而不是总量：检查之前拉 Mojang 版本清单也会发请求，
    但它失败不代表**模组数据源**不可用（实测过这个误报），限流提示同理。

    调用方通常不需要自己建它：run_check_flow() 会填好并放进 CheckOutcome。
    """

    source: StatsSource | None = None
    requests_before: int = 0
    successes_before: int = 0
    rate_limited_before: int = 0
    requests_after: int = 0
    successes_after: int = 0
    rate_limited_after: int = 0
    #: 累计请求数与缓存命中（报告头要用，与增量无关）
    requests_made: int = 0
    cache_hits: int = 0

    def _counters(self) -> tuple[int, int, int]:
        if self.source is None:
            return (0, 0, 0)
        requests, _cache_hits = self.source.stats
        return int(requests), int(self.source.successes), int(self.source.rate_limited)

    def take_before(self) -> None:
        """取检查区间的起点快照（必须在 check_all 之前调用）。"""
        self.requests_before, self.successes_before, self.rate_limited_before = self._counters()

    def take_after(self) -> None:
        """取检查区间的终点快照。"""
        self.requests_after, self.successes_after, self.rate_limited_after = self._counters()
        if self.source is not None:
            self.requests_made, self.cache_hits = self.source.stats

    @property
    def requests_delta(self) -> int:
        """检查区间内发出的请求数。"""
        return self.requests_after - self.requests_before

    @property
    def successes_delta(self) -> int:
        """检查区间内成功的请求数。"""
        return self.successes_after - self.successes_before

    @property
    def rate_limited_delta(self) -> int:
        """检查区间内收到的 429 次数。"""
        return self.rate_limited_after - self.rate_limited_before


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    """一次检查的完整结果：报告 + 运行统计。

    只有一个返回值，调用方写法统一（GUI 与 CLI 都读同一份）：

        outcome = run_check_flow(...)
        outcome.report.verdict()          # 结论
        outcome.report.groups             # 分组条目
        source_unavailable(outcome)       # 退出码 4 的判据
    """

    report: Report
    stats: CheckStats


def source_unavailable(outcome: CheckOutcome) -> bool:
    """数据源是否整体不可用（E01 -> 退出码 4）。

    判据：**本次检查期间确实发出过请求、但一次都没成功**，且没有任何模组得出结论。
    只看总量会误判：检查前拉 Mojang 版本清单失败也算"请求过"，但那不代表
    **模组数据源**不可用（实测过这个误报）。所以只统计检查区间的增量。
    """
    report, stats = outcome.report, outcome.stats
    data = report.summary
    if data["total_checked"] == 0 or data["unknown"] != data["total_checked"]:
        return False
    return stats.requests_delta > 0 and stats.successes_delta == 0


def run_check_flow(entries: Sequence[ModEntry], *, provider: "BaseProvider | None",
                   loader: Loader, mc_version: str, window: int = 25,
                   prerelease: bool = False, jobs: int = 6, resolve: bool = False,
                   on_progress: ProgressFn | None = None, on_item: ItemFn | None = None,
                   should_stop: StopFn | None = None, interactive_match: MatchFn | None = None,
                   stats_source: StatsSource | None = None, profile_name: str = "",
                   profile_saved: bool = True,
                   source_status: tuple[str, str] | None = None) -> CheckOutcome:
    """跑完一次兼容性检查，返回 CheckOutcome（报告 + 运行统计）。

    参数：
        entries: 要检查的模组条目。
        provider: 注入的数据源。
        loader / mc_version: 目标加载器与目标游戏版本。
        window: 每个项目最多看多少条版本记录。
        prerelease: 是否允许测试版参与判定。
        jobs: 并发数（core 侧硬上限 8）。
        resolve: 是否允许用名称搜索补匹配（D34：默认不发搜索请求）。
        on_progress: 每检查完一个模组回调 (已完成, 总数, 模组名)。
        on_item: 同一时刻的逐条回调 (已完成, 总数, 条目, 报告项)。
        should_stop: 返回 True 时停下（已完成的判定保留，报告会被标成 interrupted）。
        interactive_match: 交互匹配回调（仅交互模式传；默认路径绝不问、绝不猜）。
        stats_source: 请求计数器的来源（真实实现是 HttpClient）；不传就没有请求数，
            也判不了"数据源整体不可用"。
        profile_name / profile_saved / source_status: 报告头要显示的清单与数据源信息。

    返回：
        CheckOutcome。中断时 report.interrupted=True、completed 是**已完成**的条数。
    """
    entries = list(entries)
    report = Report(mc_version=str(mc_version), loader=loader, profile_name=profile_name,
                    generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                    profile_saved=profile_saved, total=len(entries))
    if source_status is not None:
        # Report 的默认文案是"Modrinth 已启用 / CurseForge 未启用"，
        # 真实状态只有调用方（registry.status_line()）知道
        report.source_status = source_status
    stats = CheckStats(stats_source)
    start = time.monotonic()
    stats.take_before()

    def on_done(done: int, total: int, entry: ModEntry, item: ReportItem) -> None:
        if on_item is not None:
            on_item(done, total, entry, item)
        if on_progress is not None:
            on_progress(done, total, entry.best_name)

    try:
        items = check_all(entries, provider, loader=loader, mc_version=str(mc_version),
                          window=window, prerelease=prerelease, jobs=jobs, resolve=resolve,
                          on_done=on_done, should_stop=should_stop,
                          interactive_match=interactive_match)
    except (UserCancelled, KeyboardInterrupt):
        # S12：中断后立刻给出"不完整报告"，绝不打印 traceback（渲染由调用方负责）。
        # 注意这里**不填**请求数、限流提示与识别来源 —— 那份报告是"查了多少算多少"。
        report.interrupted = True
        report.elapsed = time.monotonic() - start
        stats.take_after()
        return CheckOutcome(report, stats)

    for item in items:
        report.add(item)
    report.completed = len(items)
    report.elapsed = time.monotonic() - start
    # check_all 只在 should_stop() 为真时少产出条目 —— 那是"用户取消了"，不是"检查完了"
    if should_stop is not None and len(items) < len(entries):
        report.interrupted = True
    stats.take_after()
    # 被限流导致的未判定必须显式告诉用户：否则他会把这 18 条 ⚪ 当成"这些模组查不到"，
    # 而不会想到"再跑一次就有了"（实测 200 个不同项目冷跑出现过 18 条）。
    if stats.rate_limited_delta > 0 and report.summary["unknown"] > 0:
        report.warnings.append(t("warn.rate_limited_summary", count=report.summary["unknown"]))
    report.requests_made, report.cache_hits = stats.requests_made, stats.cache_hits
    for item in items:
        kind = item.mod.source_kind
        if kind is not None:
            report.source_stats[kind] = report.source_stats.get(kind, 0) + 1
    return CheckOutcome(report, stats)


__all__ = ["CheckOutcome", "CheckStats", "ItemFn", "MatchFn", "ProfileEntries", "ProgressFn",
           "StatsSource", "StopFn", "load_profile_entries", "run_check_flow",
           "source_unavailable"]
