"""报告导出实现（不新增子命令，由 check --json/--md/--csv 调用）。"""
from __future__ import annotations

import csv
import io
import json
import os
from datetime import datetime
from pathlib import Path

from modcheck.core.models import Loader, Status
from modcheck.core.report import (Report, advice_text, build_action_hints, reason_text,
                                  summary_line, verdict_line)
from modcheck.errors import ConfigError
from modcheck.i18n import t

#: 导出的 CSV 表头（固定顺序，方便贴进表格软件）
CSV_HEADER = ("status", "reason", "key", "display_name", "cn_name", "mod_id",
              "current_version", "latest_for_loader", "latest_compat",
              "max_supported_mc", "file_name", "message")


def default_filename(profile_name: str, mc: str, loader: Loader, ext: str,
                     when: datetime | None = None) -> str:
    """导出文件名自动带版本与时间：report_服务器A_26.3_fabric_20261001-2103.json。"""
    stamp = (when or datetime.now()).strftime("%Y%m%d-%H%M")
    safe = "".join(ch for ch in profile_name if ch not in '\\/:*?"<>|').strip() or "profile"
    return "report_" + safe + "_" + mc + "_" + loader.value + "_" + stamp + "." + ext


def _atomic_write(path: Path, text: str) -> None:
    """原子写文本文件；失败转成领域异常（PRD E22）。"""
    target = Path(path)
    tmp = target.with_name(target.name + ".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp, target)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise ConfigError(t("err.export.failed", path=target)) from exc


def export_json(report: Report, path: Path) -> None:
    """导出 JSON（含 schema_version，供未来 GUI 消费）。"""
    _atomic_write(path, json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n")


def export_markdown(report: Report, path: Path) -> None:
    """导出 Markdown（可以直接贴到群里）。"""
    lines: list[str] = []
    summary = report.summary
    lines.append("# " + t("app.title"))
    lines.append("")
    lines.append("- " + t("report.header.profile", name=report.profile_name,
                          count=summary["total_all"]))
    lines.append("- " + t("report.header.target", mc=report.mc_version,
                          loader=report.loader.display_name))
    lines.append("- " + t("report.header.time", time=report.generated_at,
                          elapsed=f"{report.elapsed:.0f}", requests=report.requests_made,
                          cache_hits=report.cache_hits))
    lines.append("")
    lines.append("**" + verdict_line(report) + "**")
    lines.append("")
    for status in (Status.BLOCKED, Status.DEGRADED, Status.UNKNOWN, Status.READY, Status.IGNORED):
        group = report.groups.get(status, [])
        if not group:
            continue
        lines.append("## " + t("group." + status.value + ".title", count=len(group),
                               mc=report.mc_version, loader=report.loader.display_name))
        lines.append("")
        lines.append("| # | 名称 | modid | 当前版本 | 原因 |")
        lines.append("|---|---|---|---|---|")
        for index, item in enumerate(group, start=1):
            lines.append("| " + str(index) + " | " + item.mod.best_name + " | "
                         + (item.mod.mod_id or item.mod.key) + " | "
                         + (item.current_version or "-") + " | "
                         + reason_text(item, report).replace("|", "/") + " |")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(summary_line(report))
    lines.append("")
    lines.append("\`\`\`")
    lines.extend(build_action_hints(report))
    lines.append("\`\`\`")
    _atomic_write(path, "\n".join(lines) + "\n")


def export_csv(report: Report, path: Path) -> None:
    """导出 CSV（UTF-8 BOM 让 Excel 正确识别中文）。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_HEADER)
    for item in report.iter_items():
        writer.writerow([
            item.status.value,
            item.reason.value,
            item.mod.key,
            item.mod.display_name,
            item.mod.cn_name or "",
            item.mod.mod_id or "",
            item.current_version or "",
            item.latest_for_loader.version_number if item.latest_for_loader else "",
            item.latest_compat.version_number if item.latest_compat else "",
            item.max_supported_mc or "",
            item.mod.file_name or "",
            (reason_text(item, report) + " / " + advice_text(item, report)).replace("\n", " "),
        ])
    _atomic_write(path, "\ufeff" + buffer.getvalue())


#: 模组清单交流用的默认文件名前缀
MODLIST_PREFIX = "modlist_"


def modlist_filename(profile_name: str, ext: str) -> str:
    """导出模组清单的默认文件名（与报告导出同一套命名习惯）。"""
    safe = "".join(ch for ch in profile_name if ch not in '\\/:*?"<>|').strip() or "profile"
    return MODLIST_PREFIX + safe + "." + ext


def export_modlist(profile, path: Path, *, fmt: str = "md") -> None:
    """导出**模组清单**（供服主之间交流）。

    与报告导出（export_markdown 等）**不是一回事**：
      · 报告是一次检查的结果，带状态与建议；
      · 清单只是「我这个包里有哪些模组」，与查没查过无关。
    所以这里**不下任何结论**，只列事实，外加一个能点开的链接 ——
    对方拿到后可以照着装，也可以把 JSON 那份导回自己的工具里。
    """
    target = Path(path)
    mods = list(profile.mods)
    if fmt == "json":
        _atomic_write(target, json.dumps(profile.to_dict(), ensure_ascii=False, indent=2) + "\n")
        return

    lines = [f"# 模组清单：{profile.name}", ""]
    if getattr(profile, "description", ""):
        lines += [profile.description, ""]
    ignored = sum(1 for e in mods if str(getattr(e, "match_status", "")) == "MatchStatus.IGNORED")
    lines.append(f"共 {len(mods)} 个模组。" + (f"其中 {ignored} 个已标记为忽略。" if ignored else ""))
    lines += ["", "| # | 模组 | 平台项目 | 文件名 |", "|---|------|---------|--------|"]
    for i, entry in enumerate(mods, start=1):
        name = (getattr(entry, "display_name", "") or getattr(entry, "cn_name", "")
                or getattr(entry, "file_name", "") or getattr(entry, "key", ""))
        slug = (getattr(entry, "sources", None) or {}).get("modrinth") or ""
        link = f"[{slug}](https://modrinth.com/mod/{slug})" if slug else "（未识别）"
        lines.append(f"| {i} | {name} | {link} | {getattr(entry, 'file_name', '') or ''} |")
    lines += ["", "> 本清单由 modcheck 导出，不含任何检查结论。", ""]
    _atomic_write(target, "\n".join(lines))


__all__ = ["default_filename", "export_json", "export_markdown", "export_csv", "CSV_HEADER",
           "export_modlist", "modlist_filename"]
