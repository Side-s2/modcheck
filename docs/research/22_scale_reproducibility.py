# -*- coding: utf-8 -*-
"""构造 200 条清单，试图复现 PM 报的『同一清单两次结论不同』。"""
import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
PY = ROOT / ".toolchain" / "Python311" / "python.exe"
cfg = Path(tempfile.mkdtemp(prefix="scale-"))
env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8")

def run(*args, timeout=1800):
    return subprocess.run([str(PY), "-m", "modcheck", "--config-dir", str(cfg), *args],
                          cwd=str(ROOT), env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)

run("scan", str(ROOT / "mods_sample"), "--profile", "base", "--yes")
base = json.loads((cfg / "profiles" / "base.json").read_text(encoding="utf-8"))
print(f"基础清单 {len(base['mods'])} 条")

# 克隆到 200 条（key 唯一，但 sources 指向同样的项目 -> 会被反复查询）
mods = []
for i in range(200):
    src = base["mods"][i % len(base["mods"])]
    clone = json.loads(json.dumps(src))
    clone["key"] = f"{src['key']}#{i}"
    clone["file_name"] = f"copy{i:03d}-{src.get('file_name','x')}"
    mods.append(clone)
prof = {"schema_version": 1, "name": "big", "description": "", "created_at": "", "updated_at": "", "mods": mods}
(cfg / "profiles" / "big.json").write_text(json.dumps(prof, ensure_ascii=False), encoding="utf-8")
print(f"构造清单 200 条")

import re, time
summaries = []
for i in (1, 2, 3):
    t0 = time.time()
    r = run("check", "--profile", "big", "--mc", "26.3", "--loader", "fabric",
            "--no-color", "--refresh", "--jobs", "6")
    dt = time.time() - t0
    line = next((l.strip() for l in (r.stdout or "").splitlines() if l.startswith("汇总")), "(无汇总行)")
    req = next((l.strip() for l in (r.stdout or "").splitlines() if "请求" in l and "缓存" in l), "")
    summaries.append(line)
    print(f"  第{i}次 exit={r.returncode} 用时={dt:.0f}s")
    print(f"    {line}")
    if req:
        print(f"    {req}")
    time.sleep(3)

print()
print("三次汇总是否完全一致:", len(set(summaries)) == 1)
for s in sorted(set(summaries)):
    print("   ", s)
shutil.rmtree(cfg, ignore_errors=True)
