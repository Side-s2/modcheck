"""GUI 的真实后端：与 CLI 共用 flows 的运行时装配与检查流程。

这一层存在的意义：**GUI 里不出现任何判定逻辑**。
它只做三件事 —— 取清单列表、取版本列表、把 Report 转成表格行。
所有"这个模组到底行不行"的判断都来自 core，流程编排来自 flows，
所以 GUI 与 CLI 的结论**在构造上不可能不一致**。
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

from modcheck.core.models import Loader
from modcheck.core.report import advice_text, reason_text, version_cell, verdict_line
from modcheck.errors import ProviderError
from modcheck.flows import (default_filename, export_csv, export_json, export_markdown,
                            load_profile_entries, run_check_flow)
from modcheck.flows.runtime import build_runtime
from modcheck.gui.main_window import Row
from modcheck.providers.mojang import MojangVersions
from modcheck.storage.profiles import list_profiles

#: 与 CLI 的 --window 默认值保持一致；**不得为了省流量调小**（会漏掉真正可用的版本）
DEFAULT_WINDOW = 25


def _short_date(raw: str | None) -> str:
    """ISO 时间取到日；取不到就留空（不显示 None）。"""
    text = (raw or "").strip()
    return text[:10] if len(text) >= 10 and text[4] == "-" else ""


def _mod_name(item) -> str:
    """模组显示名：优先中文名/展示名，退到文件名，最后才用 key。"""
    mod = item.mod
    for attr in ("display_name", "cn_name", "file_name", "key"):
        value = getattr(mod, attr, "") or ""
        if value:
            return str(value)
    return "（未知）"


def _to_row(item) -> Row:
    """把 core 的 ReportItem 转成界面用的行（纯搬运，不做判断）。"""
    latest = item.latest_compat or item.latest_for_loader or item.latest_any
    available = ""
    if item.status.value in ("degraded", "prerelease"):
        if item.latest_compat is not None:
            available = f"{item.latest_compat.version_number}（{_short_date(item.latest_compat.date_published)}）"
        elif item.latest_any is not None:
            available = f"{item.latest_any.version_number}（{item.latest_any.version_type} 通道）"
    reason = ""
    if item.status.value in ("blocked", "unknown"):
        reason = reason_text(item, _StubReport(item))
    elif item.status.value in ("degraded", "prerelease"):
        reason = reason_text(item, _StubReport(item))
    return Row(name=_mod_name(item), status=item.status.value, version=version_cell(item),
               date=_short_date(latest.date_published if latest else None),
               reason=reason, available=available)


class _StubReport:
    """reason_text/advice_text 需要 loader 与 mc_version；这里只透传。"""

    def __init__(self, item) -> None:
        self.loader = Loader.FABRIC
        self.mc_version = ""


class CliBackend:
    """界面用的后端实现（名字保留 Cli 前缀不合适，但先叫 Backend 更清楚）。"""

    def __init__(self, config_dir: str | Path | None = None) -> None:
        self.runtime = build_runtime(config_dir=config_dir)
        self._versions: list[str] | None = None
        #: 最近一次检查的报告 —— 导出按钮要用它（与 CLI 导出**同一份实现**）
        self.last_report = None

    # ---------------------------------------------------------------- 清单
    def profiles(self) -> Sequence[tuple[str, int]]:
        """(清单名, 模组数)。读不到就返回空列表，由界面显示"无"。"""
        try:
            return [(s.name, s.mod_count) for s in list_profiles(self.runtime.profiles_dir)]
        except Exception:
            return []

    # ---------------------------------------------------------------- 版本
    def versions(self) -> Sequence[str]:
        """官方正式版列表（最近的在前）。取不到就给空 —— 界面会显示（无），不阻塞使用。"""
        if self._versions is None:
            try:
                releases = MojangVersions(self.runtime.client).list_releases(limit=10)
                self._versions = [r.version_id for r in releases]
            except ProviderError:
                self._versions = []
        return self._versions

    # ---------------------------------------------------------------- 检查
    def run(self, profile: str, mc: str, loader: str,
            on_progress: Callable[[int, int, str], None],
            should_stop: Callable[[], bool], *, window: int = DEFAULT_WINDOW,
            prerelease: bool = False) -> tuple[str, list[Row]]:
        """跑一次检查。**任何判定都不在这里发生** —— 全部来自 flows/core。

        window/prerelease 与 CLI 的同名参数**默认值必须一致**（25 / False）：
        它们是判定口径的一部分，两边不一致就会出现"同一个模组在 CLI 与 GUI 里结论不同"。
        """
        settings = self.runtime.settings
        # ⚠️ primary 是**方法**不是属性：写成 registry.primary 会把方法对象当数据源传进去，
        # 结果是每个模组都抛异常 -> 全部 ⚪「未判定」。实测踩过（30 个模组全查不出来）。
        provider = self.runtime.registry.primary()
        loaded = load_profile_entries(profiles_dir=self.runtime.profiles_dir,
                                      profile=profile, provider=provider,
                                      on_progress=on_progress, should_stop=should_stop)
        outcome = run_check_flow(
            loaded.entries, provider=provider,
            loader=Loader.parse(loader.strip().lower()), mc_version=mc,
            window=int(window), prerelease=bool(prerelease),
            jobs=int(settings.concurrency), on_progress=on_progress,
            should_stop=should_stop, stats_source=self.runtime.client,
            profile_name=loaded.name, profile_saved=loaded.saved)
        self.last_report = outcome.report
        rows = [_to_row(item) for item in outcome.report.iter_items()]
        return verdict_line(outcome.report), rows

    # ---------------------------------------------------------------- 导出
    def export_default_name(self, fmt: str) -> str:
        """默认文件名（与 CLI 的命名规则一致）。"""
        report = self.last_report
        if report is None:
            return "report." + fmt
        return default_filename(report.profile_name, report.mc_version, report.loader, fmt)

    def export_to(self, path: str | Path, fmt: str) -> Path:
        """导出报告。**复用 flows.export**，所以 GUI 导出的文件与 CLI 导出的逐字节相同。"""
        if self.last_report is None:
            raise RuntimeError("还没有可导出的报告")
        target = Path(path)
        if fmt == "json":
            export_json(self.last_report, target)
        elif fmt == "md":
            export_markdown(self.last_report, target)
        else:
            export_csv(self.last_report, target)
        return target


__all__ = ["CliBackend"]
