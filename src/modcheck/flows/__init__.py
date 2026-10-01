"""流程编排层（flows）：CLI 与 GUI 共用同一套流程。

分层（docs/GUI_DESIGN.md §1）：

    core/     纯判定与数据：无 IO、无 print/input、不依赖 cli 或 gui
      ↓
    flows/    流程编排：扫描识别、兼容性检查、下载
              进度用 on_progress 回调、取消用 should_stop 探针，
              返回结构化结果（ScanReport / Report / DownloadOutcome），**不打印任何东西**
      ↓
    cli/      只做三件事：解析参数 → 调 flow → 渲染成终端文本
    gui/      只做三件事：Qt 控件 → 调 flow → 更新界面（一期）

这条边界是 GUI 能复用流程的前提：flows 一旦沾上终端输出，GUI 就得另写一份，
两份逻辑早晚漂移。docs/research/36_layering_check.py 会静态检查它。
"""
from modcheck.flows.export import (CSV_HEADER, default_filename, export_csv, export_json,
                                   export_markdown)
from modcheck.flows.runtime import Runtime, build_runtime
from modcheck.flows.check_flow import (CheckOutcome, CheckStats, ProfileEntries,
                                       load_profile_entries, run_check_flow,
                                       source_unavailable)
from modcheck.flows.scan_flow import (DEFAULT_PROFILE, HASH_BATCH, ScanReport, SkipItem,
                                      scan_dirs, scan_from_list)
from modcheck.flows.download_flow import (DEFAULT_JOBS, DEFAULT_RETRIES, DownloadOutcome,
                                          DownloadPrep, DownloadSummary, TargetCheck,
                                          check_target_dir, ensure_target_dir,
                                          looks_like_mods_dir, prepare_download,
                                          run_download_flow)

__all__ = [
    "CheckOutcome", "CheckStats", "ProfileEntries", "load_profile_entries", "run_check_flow",
    "source_unavailable",
    "DEFAULT_PROFILE", "HASH_BATCH", "ScanReport", "SkipItem", "scan_dirs", "scan_from_list",
    "DEFAULT_JOBS", "DEFAULT_RETRIES", "DownloadOutcome", "DownloadPrep", "DownloadSummary",
    "TargetCheck", "check_target_dir", "ensure_target_dir", "looks_like_mods_dir",
    "prepare_download", "run_download_flow",
    "Runtime", "build_runtime",
    "CSV_HEADER", "default_filename", "export_csv", "export_json", "export_markdown",
]
