# -*- coding: utf-8 -*-
"""归一化配置目录路径后再比对（那三个用例的输出里本来就带 temp 路径）。"""
import os, re, subprocess, shutil, sys, tempfile
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
PY = ROOT / ".toolchain" / "Python311" / "python.exe"
gold = ROOT / "docs" / "research" / "golden"
env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8", NO_COLOR="1")

def norm(text: str, cfgdir: str) -> str:
    """把配置目录路径（含正反斜杠、大小写差异）统一成占位符。"""
    out = text.replace(cfgdir, "<CFG>")
    out = re.sub(r"[A-Za-z]:\\\\?[^\s]*?(golden|mygold|dsh)-[A-Za-z0-9_\\-]+", "<CFG>", out)
    out = re.sub(r"<CFG>[\\\\/]", "", out)
    return out

tmp = Path(tempfile.mkdtemp(prefix="mygold-"))
src = (ROOT / "docs" / "research" / "39_golden_snapshot.py").read_text(encoding="utf-8")
(src_out := tmp / "run39.py").write_text(
    src.replace('OUT = ROOT / "docs" / "research" / "golden"', f'OUT = Path(r"{tmp}")'),
    encoding="utf-8")
subprocess.run([str(PY), str(src_out)], cwd=str(ROOT), env=env, capture_output=True,
               text=True, encoding="utf-8", errors="replace", timeout=600)

# 两种归一化都试：临时目录名整体替换
same, diff, samples = 0, [], []
for f in sorted(gold.glob("*")):
    other = tmp / f.name
    if not other.exists():
        diff.append(f.name); continue
    a, b = f.read_text(encoding="utf-8", errors="replace"), other.read_text(encoding="utf-8", errors="replace")
    na = re.sub(r"[A-Za-z]:\\\\?[^\r\n]*?(golden|mygold)-[A-Za-z0-9_\\-]+", "<CFG>", a)
    nb = re.sub(r"[A-Za-z]:\\\\?[^\r\n]*?(mygold|golden)-[A-Za-z0-9_\\-]+", "<CFG>", b)
    if na == nb:
        same += 1
    else:
        diff.append(f.name)
        if len(samples) < 3:
            samples.append((f.name, na.strip()[:120], nb.strip()[:120]))

print(f"归一化后比对：一致 {same} ｜ 不同 {len(diff)}")
if diff:
    print("  仍不一致：" + ", ".join(diff))
    for n, a, b in samples:
        print(f"   ── {n}\n      仓库: {a}\n      本次: {b}")
else:
    print("  ✅ 归一化掉配置目录路径后，全部逐字节一致")
shutil.rmtree(tmp, ignore_errors=True)
