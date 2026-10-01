# -*- coding: utf-8 -*-
"""X2 输出净化基线：跑一组真实命令，扫描用户可见输出里的内部标识/英文异常/argparse 原文。"""
import os, re, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
PY = ROOT / ".toolchain" / "Python311" / "python.exe"
PATTERNS = ["«", "»", "slug:", "sha1:", "invalid choice", "usage:", "Usage:",
            "Traceback", "Expecting property name", "[WinError", "unrecognized arguments",
            "AttributeError", "KeyError", "TypeError"]

cfg = Path(tempfile.mkdtemp(prefix="x2-"))
env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8", NO_COLOR="1")

def run(*args, timeout=600):
    return subprocess.run([str(PY), "-m", "modcheck", "--config-dir", str(cfg), *args],
                          cwd=str(ROOT), env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)

run("scan", str(ROOT / "mods_sample"), "--profile", "demo", "--yes")

CASES = [
    ("报告（管道）", ["check", "--profile", "demo", "--mc", "26.3", "--loader", "fabric", "--no-color"]),
    ("报告 26.1", ["check", "--profile", "demo", "--mc", "26.1", "--loader", "fabric", "--no-color"]),
    ("清单列表", ["profile", "list"]),
    ("清单详情", ["profile", "show", "demo"]),
    ("版本列表", ["versions", "--limit", "5"]),
    ("设置查看", ["config", "show"]),
    ("缓存信息", ["cache", "info"]),
    ("非法 loader", ["check", "--loader", "quilt"]),
    ("非法子命令", ["frobnicate"]),
    ("未知参数", ["--bogus"]),
    ("不存在的清单", ["check", "--profile", "nope", "--mc", "26.3", "--loader", "fabric"]),
]

print("=" * 92)
hits_total = 0
for label, args in CASES:
    try:
        r = run(*args)
        blob = (r.stdout or "") + "\n" + (r.stderr or "")
    except subprocess.TimeoutExpired:
        print(f"  [TIMEOUT] {label}  —— 命令挂死（严重）"); hits_total += 1; continue
    found = []
    for p in PATTERNS:
        if p in blob:
            for line in blob.splitlines():
                if p in line:
                    found.append(f"{p!r} @ {line.strip()[:70]}")
                    break
    if found:
        hits_total += len(found)
        print(f"  [LEAK] {label:16s} exit={r.returncode}")
        for f in found[:3]:
            print(f"           {f}")
    else:
        print(f"  [ok]   {label:16s} exit={r.returncode}")
print("=" * 92)
print(f"命中总数 = {hits_total}")
import shutil; shutil.rmtree(cfg, ignore_errors=True)
