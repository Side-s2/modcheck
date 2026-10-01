# -*- coding: utf-8 -*-
"""分层自检：core/ 与 storage/ 不得依赖 cli/，且不得直接 print/input/sys.exit。

这是"未来要封装 GUI"的硬约束：core 一旦沾上 IO，GUI 就没法复用它。
"""
import ast
import sys
from pathlib import Path

ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker") / "src" / "modcheck"
BAD_IMPORTS = ("modcheck.cli",)
BAD_CALLS = {"print", "input", "exit", "quit"}
BAD_ATTRS = {("sys", "exit"), ("os", "system")}

problems: list[str] = []
checked = 0
for layer in ("core", "storage"):
    for path in sorted((ROOT / layer).rglob("*.py")):
        checked += 1
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = f"{layer}/{path.name}"
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith(BAD_IMPORTS):
                        problems.append(f"{rel}:{node.lineno} import {a.name}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.startswith(BAD_IMPORTS):
                    problems.append(f"{rel}:{node.lineno} from {mod}")
            elif isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Name) and f.id in BAD_CALLS:
                    problems.append(f"{rel}:{node.lineno} 调用 {f.id}()")
                if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) \
                        and (f.value.id, f.attr) in BAD_ATTRS:
                    problems.append(f"{rel}:{node.lineno} 调用 {f.value.id}.{f.attr}()")

print("=" * 84)
print(f"检查了 {checked} 个 core/storage 模块")
print("=" * 84)
if problems:
    print("发现分层违规：")
    for p in problems:
        print("  ✗ " + p)
else:
    print("  ✅ core/ 与 storage/ 不依赖 cli/，且没有 print/input/sys.exit")
print()
print("新增模块是否被覆盖：")
for name in ("core/profile_ops.py", "core/settings_ops.py", "core/downloader.py"):
    print(f"  {'✅' if (ROOT / name).exists() else '❌'} {name}")
