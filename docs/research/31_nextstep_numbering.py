# -*- coding: utf-8 -*-
"""找出「下一步」断号的确切场景：枚举几种分组组合，打印下一步段落。"""
import json, os, re, subprocess, tempfile
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
PY = ROOT / ".toolchain" / "Python311" / "python.exe"
env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8", NO_COLOR="1")

def run(cfg, *a, timeout=900):
    return subprocess.run([str(PY), "-m", "modcheck", "--config-dir", str(cfg), *a],
                          cwd=str(ROOT), env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)

def show(label, cfg, *a):
    r = run(cfg, *a)
    o = r.stdout or ""
    m = re.search(r"🟢 就绪 (\d+)", o); m2 = re.search(r"🟡 需降级 (\d+)", o)
    m3 = re.search(r"🔴 阻塞 (\d+)", o); m4 = re.search(r"⚪ 未判定 (\d+)", o)
    print(f"--- {label} ---")
    print(f"    分组: 🟢{m.group(1) if m else '?'} 🟡{m2.group(1) if m2 else '?'} "
          f"🔴{m3.group(1) if m3 else '?'} ⚪{m4.group(1) if m4 else '?'}   exit={r.returncode}")
    lines = o.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("下一步")), None)
    if start is None:
        print("    （无『下一步』段落）")
    else:
        seg = [l for l in lines[start:start+6] if l.strip()]
        for l in seg:
            print("    |" + l)
        nums = re.findall(r"^\s*(\d+)\.", "\n".join(seg), re.M)
        print(f"    编号序列 = {nums}" + ("   ⚠ 断号！" if nums and nums != [str(i+1) for i in range(len(nums))] else "   ✅ 连续"))
    print()

# 场景 A：全部 ⚪（清单里全是没有 sources 的条目）
cfgA = Path(tempfile.mkdtemp(prefix="nx-a-")); (cfgA/"profiles").mkdir()
mods = [{"key": f"unk{i}", "display_name": f"Unknown{i}", "mod_id": None,
         "file_name": f"unk{i}.jar", "sources": {}, "detected": {},
         "match_status": "unmatched", "notes": "", "added_at": "", "updated_at": ""}
        for i in range(3)]
(cfgA/"profiles"/"u.json").write_text(json.dumps(
    {"schema_version":1,"name":"u","description":"","created_at":"","updated_at":"","mods":mods},
    ensure_ascii=False), encoding="utf-8")
show("场景A：全 ⚪（3 个未匹配）", cfgA, "check","--profile","u","--mc","26.3","--loader","fabric","--no-color")

# 场景 B：真实 26.3（🔴 + 🟡）
cfgB = Path(tempfile.mkdtemp(prefix="nx-b-"))
run(cfgB, "scan", str(ROOT/"mods_sample"), "--profile","s","--yes")
show("场景B：🔴 + 🟡（真实 30 模组 @26.3）", cfgB, "check","--profile","s","--mc","26.3","--loader","fabric","--no-color")

# 场景 C：真实 26.1（只有 🟡，无 🔴）
show("场景C：只有 🟡（真实 30 模组 @26.1）", cfgB, "check","--profile","s","--mc","26.1","--loader","fabric","--no-color")

import shutil
for d in (cfgA, cfgB): shutil.rmtree(d, ignore_errors=True)
