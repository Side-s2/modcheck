# -*- coding: utf-8 -*-
"""用【显示宽度】而非字符下标，验证 profile show 表头与数据行是否对齐。"""
import subprocess, sys, tempfile, unicodedata
from pathlib import Path

ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
PY = ROOT / ".toolchain" / "Python311" / "python.exe"

def dw(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in ("F", "W") else 1 for c in s)

def starts(line: str) -> list[tuple[int, int]]:
    """返回每个字段的 (字符下标, 显示列)。行首 2 空格 + 字段，字段之间是空格。"""
    out, i = [], 0
    while i < len(line):
        if line[i] != " ":
            j = i
            while j < len(line) and line[j] != " ":
                j += 1
            out.append((i, dw(line[:i])))
            i = j
        else:
            i += 1
    return out

cfg = Path(tempfile.mkdtemp(prefix="mvc-align-"))
env = dict(__import__("os").environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8")
subprocess.run([str(PY), "-m", "modcheck", "--config-dir", str(cfg), "scan",
                str(ROOT / "mods_sample"), "--profile", "d", "--yes"],
               cwd=ROOT, env=env, capture_output=True)
r = subprocess.run([str(PY), "-m", "modcheck", "--config-dir", str(cfg), "profile", "show", "d"],
                   cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")
lines = r.stdout.splitlines()
hdr = next((l for l in lines if "名称" in l), None)
rows = [l for l in lines if l.strip()[:2].strip().isdigit() and "文件指纹" in l or (l.strip()[:1].isdigit() and dw(l) > 30)]
row = next((l for l in lines if l.lstrip()[:1].isdigit() and "指纹" in l), None)

print("表头:", repr(hdr))
print("数据:", repr(row))
print()
hs, rs = starts(hdr or ""), starts(row or "")
print(f"{'列':<4}{'表头(字符,显示列)':<24}{'数据(字符,显示列)':<24}对齐?")
ok = True
for i, ((hc, hd), (rc, rd)) in enumerate(zip(hs, rs)):
    same = (hd == rd)
    ok &= same
    print(f"{i:<4}{str((hc, hd)):<24}{str((rc, rd)):<24}{'OK' if same else 'MISALIGNED'}")
if len(hs) != len(rs):
    ok = False
    print(f"  列数不同：表头 {len(hs)} 列，数据 {len(rs)} 列")
print()
print("结论:", "✅ 表头与数据行按显示宽度完全对齐" if ok else "❌ 存在错列")

import shutil; shutil.rmtree(cfg, ignore_errors=True)
raise SystemExit(0 if ok else 1)
