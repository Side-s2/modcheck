"""报告导出（转发到 flows.export）。

实现已下沉到 flows/export.py —— 它是**纯文件写入、不依赖 Console**，
CLI 与 GUI 都要用它（GUI 的「导出 JSON / Markdown」按钮走的就是同一份实现）。
放在 cli/commands/ 里的历史原因是它由 check --json/--md/--csv 调用，
但那个位置让 GUI 无法复用（GUI 不该 import cli）。
这里只保留旧路径的转发，避免动到既有 import 与测试。
"""
from modcheck.flows.export import (CSV_HEADER, default_filename, export_csv, export_json,
                                   export_markdown)

__all__ = ["CSV_HEADER", "default_filename", "export_csv", "export_json", "export_markdown"]
