# -*- coding: utf-8 -*-
"""Linux 兼容性的可验证项（本机无法真跑 Linux，只能做这些）："""
import re, sys
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
issues = []

# 1) 测试套件里有没有 Windows-only 假设
for p in (ROOT / "tests").rglob("*.py"):
    txt = p.read_text(encoding="utf-8")
    for i, line in enumerate(txt.splitlines(), 1):
        if re.search(r'"\\\\\\\\|C:\\\\\\\\|os\.name\s*==\s*.nt.', line) and "skipif" not in line:
            issues.append(f"{p.name}:{i} 疑似 Windows-only 假设: {line.strip()[:70]}")
        if "sys.platform" in line and "skipif" not in line and "win32" in line:
            issues.append(f"{p.name}:{i} 平台分支（确认是否影响 Linux）: {line.strip()[:70]}")

# 2) 源码里是否用了 pathlib（跨平台）而不是字符串拼路径
bad_paths = 0
for p in (ROOT / "src").rglob("*.py"):
    txt = p.read_text(encoding="utf-8")
    bad_paths += len(re.findall(r'Path\([^)]*\)\s*/\s*"', txt))  # 这是正确用法，反向统计
    for i, line in enumerate(txt.splitlines(), 1):
        if re.search(r'["\'][A-Za-z0-9_]+/["\']\s*\+|os\.path\.join', line):
            issues.append(f"{p.name}:{i} 字符串拼路径: {line.strip()[:70]}")

print("测试套件与源码的跨平台检查：")
print("  " + ("✅ 未发现 Windows-only 假设" if not issues else "\n  ".join(issues[:10])))
print()
print(f"  pathlib 正确用法出现 {bad_paths} 处（越多越好）")
print()
print("结论：本机无 Linux 运行时（Docker 守护未启动、WSL 无发行版），")
print("      因此 **Linux 只做了静态审计，未做运行时验证** —— 这是必须写进交付说明的已知局限。")
