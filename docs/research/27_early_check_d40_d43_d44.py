# -*- coding: utf-8 -*-
"""早期检查：D40（同版本号不得判黄）/ D43（下一步计数）/ D44（分隔线宽度）当前是否已落地。"""
import json, os, subprocess, sys, tempfile, unicodedata
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
PY = ROOT / ".toolchain" / "Python311" / "python.exe"
cfg = Path(tempfile.mkdtemp(prefix="early-"))
env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8", NO_COLOR="1")
def run(*a, timeout=900):
    return subprocess.run([str(PY), "-m", "modcheck", "--config-dir", str(cfg), *a],
                          cwd=str(ROOT), env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
def dw(s): return sum(2 if unicodedata.east_asian_width(c) in ("F","W") else 1 for c in s)

run("scan", str(ROOT/"mods_sample"), "--profile", "s", "--yes")

print("=" * 88)
print("D40：🟡 组里是否还有『同版本号』条目（有 -> 未落地）")
print("=" * 88)
for mc in ("26.3", "26.1"):
    out = cfg / f"e-{mc}.json"
    run("check", "--profile", "s", "--mc", mc, "--loader", "fabric", "--no-color", "--json", str(out))
    if not out.exists():
        print(f"  {mc}: 未产出 JSON"); continue
    d = json.loads(out.read_text(encoding="utf-8"))
    y = (d.get("groups") or {}).get("degraded") or []
    same = []
    for it in y:
        lc = (it.get("latest_compat") or {}).get("version_number")
        lf = (it.get("latest_for_loader") or {}).get("version_number")
        if lc and lf and lc == lf:
            same.append(((it.get("mod") or {}).get("file_name"), lc))
    print(f"  {mc}: 🟡 共 {len(y)} 条，其中同版本号 {len(same)} 条 {same[:3] if same else '✅'}")

print()
print("=" * 88)
print("D43：🟡 总数 vs 「下一步」计数")
print("=" * 88)
import re
r = run("check", "--profile", "s", "--mc", "26.1", "--loader", "fabric", "--no-color")
o = r.stdout or ""
m_total = re.search(r"🟡 需降级（(\d+) 个）", o)
m_next = re.search(r"拍板\s*🟡\s*的\s*(\d+)\s*个", o)
print(f"  🟡 总数 = {m_total.group(1) if m_total else '?'}    下一步计数 = {m_next.group(1) if m_next else '?'}")
print(f"  出现『无需处理』= {'无需处理' in o}")
print(f"  -> {'✅ 已区分' if (m_total and m_next and int(m_next.group(1)) < int(m_total.group(1))) else '❌ 未区分（D43 未落地）'}")

print()
print("=" * 88)
print("D44：分隔线宽度 vs 最宽数据行")
print("=" * 88)
# 口径修正（主 Agent 自纠）：D44 说的是「分隔线 == 表格宽度」，
# 因此只能与【表格行】比较 —— 汇总行/结论行是散文，本来就可能更长。
lines = [l for l in o.splitlines() if l.strip()]
seps = [dw(l) for l in lines if l.startswith("═")]
groups = [dw(l) for l in lines if l.startswith("─")]
table = [dw(l) for l in lines if l.lstrip()[:1] in "✓!✗?·"]
prose = [dw(l) for l in lines if l not in ("",) and not l.startswith(("═", "─"))
         and l.lstrip()[:1] not in "✓!✗?·"]
print(f"  分隔线 ═ : {sorted(set(seps))}")
print(f"  组标题 ─ : {sorted(set(groups))}")
print(f"  表格行   : 最大 {max(table) if table else 0}")
print(f"  散文行   : 最大 {max(prose) if prose else 0}（不参与 D44 判定）")
ok = seps and table and max(seps) == max(table) and (not groups or max(groups) == max(table))
print(f"  -> {'✅ 分隔线/组标题与表格宽度一致' if ok else '❌ 不一致（D44 未落地）'}")
if prose and table and max(prose) > max(table):
    print(f"  （备注）散文行比表格宽 {max(prose) - max(table)} 列，属排版细节，不计为 D44 失败")
import shutil; shutil.rmtree(cfg, ignore_errors=True)
