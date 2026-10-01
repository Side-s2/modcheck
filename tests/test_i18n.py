"""i18n 层测试：key 全覆盖、模板可格式化、没有未替换的花括号。"""
from __future__ import annotations

import string

from modcheck import i18n

#: T-03 明确要求必须存在的 key（节选 + 实现用到的全部关键 key）
REQUIRED_KEYS = (
    "app.title", "menu.item.check", "menu.item.scan", "menu.item.manage",
    "menu.item.settings", "menu.item.versions", "menu.item.quit", "menu.hint.no_profile",
    "report.header.title", "report.header.profile", "report.header.target",
    "report.header.sources", "report.header.origin", "report.header.time",
    "verdict.all_ready", "verdict.ready_with_degraded", "verdict.blocked",
    "verdict.incomplete", "verdict.all_unknown", "verdict.all_blocked",
    "verdict.empty", "verdict.interrupted",
    "group.blocked.title", "group.degraded.title", "group.unknown.title",
    "group.ready.title", "group.ignored.title",
    "report.summary", "report.next.title", "report.next.step1", "report.next.step2",
    "report.next.step3", "report.next.command", "report.next.none",
    "report.empty.next1", "report.empty.next2",
    "report.origin.guess_note", "report.origin.guess_hint",
    "progress.line.full", "progress.line.mid", "progress.line.short", "progress.line.tiny",
    "progress.interrupted", "progress.rate_limited",
    "scan.header", "scan.read", "scan.hash", "scan.skipped.header",
    "scan.identify.header", "scan.identify.hash", "scan.identify.meta",
    "scan.summary", "scan.profile_file",
    "match.warn.title", "match.candidates.header", "match.manual.prompt",
    "match.recorded", "match.skipped", "match.ignored", "match.noninteractive",
    "err.mc.invalid", "err.mc.snapshot", "err.mc.unknown", "err.loader.unsupported",
    "err.profile.not_found", "err.profile.exists", "err.profile.corrupt",
    "err.profile.schema", "err.dir.not_found", "err.export.failed",
    "err.source.none", "err.net.offline", "err.http.5xx", "err.rate_limited",
    "err.timeout", "err.parse.provider", "err.cert", "err.hash.miss",
    "err.config_dir.not_writable", "err.internal",
)


def test_required_keys_exist() -> None:
    """T-03 要求的 key 一个都不能少。"""
    missing = [key for key in REQUIRED_KEYS if not i18n.has(key)]
    assert missing == []


def test_missing_key_returns_marker() -> None:
    """缺失 key 返回 «key»，不抛异常。"""
    assert i18n.t("no.such.key.exists") == "«no.such.key.exists»"


def test_every_template_formats() -> None:
    """所有模板都能用占位符自身作为值格式化（能抓出多余/残缺的花括号）。"""
    for key in i18n.keys():
        template = i18n.t(key, **{})
        fields = {name for _, name, _, _ in string.Formatter().parse(template) if name}
        rendered = i18n.t(key, **{name: "X" for name in fields})
        assert "{" not in rendered, key
        assert "}" not in rendered, key


def test_tn_passes_n() -> None:
    """tn 把数量塞进 n。"""
    assert i18n.tn("unit.count", 3) == "3 个"


def test_exact_wording_samples() -> None:
    """逐字抽查 PRD §5 的文案（全角标点与空格都不能变）。"""
    assert i18n.t("verdict.all_ready", mc="26.3", loader="Fabric", total=5) == (
        "结论：✅ 可以升级到 Minecraft 26.3（Fabric）—— 5 个模组全部就绪"
    )
    assert i18n.t("err.loader.unsupported", value="quilt") == (
        "✗ 暂不支持加载器「quilt」。目前支持：fabric、neoforge、forge。"
    )
    assert i18n.t("group.ready.title", count=5, mc="26.3", loader="Fabric") == (
        "🟢 就绪（5 个）  已经支持 MC 26.3 + Fabric，无需处理"
    )
