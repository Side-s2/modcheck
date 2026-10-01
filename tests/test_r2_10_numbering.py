"""R2-10：「下一步」编号必须连续（主 Agent 枚举的三个真实场景）。"""
from __future__ import annotations

import re

import pytest

from modcheck.core.models import Loader, ModEntry, ReasonCode, Status, VersionInfo
from modcheck.core.report import Report, ReportItem, build_action_hints

_STEP_RE = re.compile(r"^\s*(\d+)\.")


def V(number: str) -> VersionInfo:
    """构造版本对象。"""
    return VersionInfo(version_id="V", version_number=number, name=number, project_id="P",
                       date_published="2026-09-18T00:00:00Z", version_type="release",
                       game_versions=("26.3",), loaders=("fabric",), files=())


def entry(key: str, status: Status, reason: ReasonCode, **kw: object) -> ReportItem:
    """构造条目。"""
    mod = ModEntry(key=key, display_name=key, mod_id=key,
                   current_version=kw.pop("current", None))  # type: ignore[arg-type]
    return ReportItem(mod=mod, status=status, reason=reason, reason_key="reason.x",
                      hint_key="advice.x", **kw)  # type: ignore[arg-type]


def build(*items: ReportItem) -> Report:
    """构造报告。"""
    report = Report(mc_version="26.3", loader=Loader.FABRIC, profile_name="u", generated_at="t")
    for item in items:
        report.add(item)
    return report


def scenario_a() -> Report:
    """场景 A：3 个未匹配（全 ⚪）—— 修复前只输出 "3."。"""
    return build(*[entry("m" + str(i), Status.UNKNOWN, ReasonCode.UNMATCHED) for i in range(3)])


def scenario_b() -> Report:
    """场景 B：🟢+🟡+🔴（无 ⚪）—— 修复前本来就连续。"""
    items = [entry("r" + str(i), Status.READY, ReasonCode.OK) for i in range(21)]
    items.append(entry("d1", Status.DEGRADED, ReasonCode.OLD_VERSION_ONLY, current="1.0",
                       latest_compat=V("2.0"), latest_for_loader=V("3.0")))
    items.append(entry("b1", Status.BLOCKED, ReasonCode.NO_MC_VERSION))
    return build(*items)


def scenario_c() -> Report:
    """场景 C：🟢+🟡（无 🔴 无 ⚪）—— 修复前只输出 "2."。"""
    items = [entry("r" + str(i), Status.READY, ReasonCode.OK) for i in range(8)]
    items.append(entry("d1", Status.DEGRADED, ReasonCode.OLD_VERSION_ONLY, current="1.0",
                       latest_compat=V("2.0"), latest_for_loader=V("3.0")))
    return build(*items)


@pytest.mark.parametrize("factory", [scenario_a, scenario_b, scenario_c])
def test_step_numbers_are_contiguous(factory) -> None:
    """编号序列必须是 1..n（不依赖具体文案，文案改了也不会失效）。"""
    hints = build_action_hints(factory())
    numbers = [int(match.group(1)) for line in hints if (match := _STEP_RE.match(line))]
    assert numbers, hints
    assert numbers == list(range(1, len(numbers) + 1)), (numbers, hints)


def test_scenario_a_starts_at_one() -> None:
    """场景 A：只有 ⚪ 项时编号必须从 1 开始（修复前是 3）。"""
    hints = build_action_hints(scenario_a())
    first = next(line for line in hints if _STEP_RE.match(line))
    assert first.strip().startswith("1.")
    assert "查清楚" in first


def test_scenario_c_starts_at_one() -> None:
    """场景 C：只有 🟡 项时编号必须是 1（修复前是 2）。"""
    hints = build_action_hints(scenario_c())
    first = next(line for line in hints if _STEP_RE.match(line))
    assert first.strip().startswith("1.")
