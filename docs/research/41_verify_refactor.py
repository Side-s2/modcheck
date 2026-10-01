# -*- coding: utf-8 -*-
"""主 Agent 对流程下沉重构的独立复核（不信任"看着差不多"）。"""
import ast, filecmp, os, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
PY = ROOT / ".toolchain" / "Python311" / "python.exe"
env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8", NO_COLOR="1")

print("=" * 88)
print("① flows/ 是否偷偷依赖 cli（这次重构的核心约束）")
print("=" * 88)
bad = []
for p in sorted((ROOT / "src" / "modcheck" / "flows").glob("*.py")):
    tree = ast.parse(p.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bad += [f"{p.name}:{node.lineno} import {a.name}" for a in node.names
                    if a.name.startswith("modcheck.cli")]
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("modcheck.cli"):
            bad.append(f"{p.name}:{node.lineno} from {node.module}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in ("print", "input"):
            bad.append(f"{p.name}:{node.lineno} 调用 {node.func.id}()")
print("  " + ("✅ flows/ 不依赖 cli，且无 print/input" if not bad else "❌ " + "; ".join(bad)))

print()
print("=" * 88)
print("② 逐字快照对比（我自己重跑一遍，不信转述）")
print("=" * 88)
gold = ROOT / "docs" / "research" / "golden"
tmp = Path(tempfile.mkdtemp(prefix="mygold-"))
# 把关卡里的快照脚本指向临时输出
script_src = (ROOT / "docs" / "research" / "39_golden_snapshot.py").read_text(encoding="utf-8")
patched = script_src.replace('OUT = ROOT / "docs" / "research" / "golden"',
                             f'OUT = Path(r"{tmp}")')
mine = tmp / "run39.py"
mine.write_text(patched, encoding="utf-8")
r = subprocess.run([str(PY), str(mine)], cwd=str(ROOT), env=env, capture_output=True,
                   text=True, encoding="utf-8", errors="replace", timeout=600)
diff, same = [], 0
for f in sorted(gold.glob("*")):
    if f.name == "run39.py":
        continue
    other = tmp / f.name
    if not other.exists():
        diff.append(f"{f.name} 缺失")
    elif f.read_bytes() != other.read_bytes():
        diff.append(f.name)
    else:
        same += 1
print(f"  比对 {same + len(diff)} 个文件：逐字节一致 {same} ｜ 不同 {len(diff)}")
if diff:
    print("  ❌ 不一致：" + ", ".join(diff[:8]))
else:
    print("  ✅ 全部逐字节一致")

print()
print("=" * 88)
print("③ 分层自检（含 flows/）")
print("=" * 88)
r2 = subprocess.run([str(PY), str(ROOT / "docs" / "research" / "36_layering_check.py")],
                    cwd=str(ROOT), env=env, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=180)
print("  " + "\n  ".join(l for l in r2.stdout.splitlines() if "✅" in l or "✗" in l or "检查了" in l))
shutil.rmtree(tmp, ignore_errors=True)
