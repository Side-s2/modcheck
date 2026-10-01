# -*- coding: utf-8 -*-
import os, subprocess, sys, tempfile, unicodedata
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
PY = ROOT / ".toolchain" / "Python311" / "python.exe"
cfg = Path(tempfile.mkdtemp(prefix="w-"))
env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8", NO_COLOR="1")
subprocess.run([str(PY), "-m", "modcheck", "--config-dir", str(cfg), "scan", str(ROOT/"mods_sample"),
                "--profile", "s", "--yes"], cwd=str(ROOT), env=env, capture_output=True)
r = subprocess.run([str(PY), "-m", "modcheck", "--config-dir", str(cfg), "check", "--profile", "s",
                    "--mc", "26.3", "--loader", "fabric", "--no-color"],
                   cwd=str(ROOT), env=env, capture_output=True, text=True, encoding="utf-8")
def dw(s): return sum(2 if unicodedata.east_asian_width(c) in ("F","W") else 1 for c in s)
lines = r.stdout.splitlines()
groups = {}
for ln in lines:
    if not ln.strip(): continue
    w = dw(ln)
    key = "分隔线(═)" if ln.startswith("═") else ("组标题(─)" if ln.startswith("─") else "其它")
    groups.setdefault(key, []).append(w)
print("输出宽度分布（按显示列）：")
for k, v in groups.items():
    print(f"  {k:12s} 行数={len(v):3d}  最小={min(v):4d}  最大={max(v):4d}")
print()
print("前 14 行的显示宽度：")
for ln in lines[:14]:
    print(f"  {dw(ln):4d}  |{ln[:96]}")
import shutil; shutil.rmtree(cfg, ignore_errors=True)
