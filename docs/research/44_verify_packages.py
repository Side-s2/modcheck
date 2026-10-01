# -*- coding: utf-8 -*-
"""打包产物真机验证：三个产物都必须能跑，且 CLI 结论与源码版逐字一致。"""
import os, subprocess, sys, tempfile, time
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
PY = ROOT / ".toolchain" / "Python311" / "python.exe"
cfg = Path(tempfile.mkdtemp(prefix="pkg-verify-"))
env = dict(os.environ, PYTHONIOENCODING="utf-8", NO_COLOR="1")

def run(label, cmd, timeout=600):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, env=env)
    return p

print("=== 1) CLI 单文件：版本 ===")
one = ROOT / "dist" / "modcheck.exe"
p = run("onefile", [str(one), "--version"])
print("   ", p.stdout.strip() or p.stderr.strip()[:120])

print("=== 2) CLI 单文件：真实检查（必须复现源码版结论）===")
# 先用源码版建清单（避免打包版首次运行还要扫）
subprocess.run([str(PY), "-m", "modcheck", "--config-dir", str(cfg), "scan",
                str(ROOT / "mods_sample"), "--profile", "s", "--yes"],
               cwd=str(ROOT), env=dict(env, PYTHONPATH=str(ROOT / "src")),
               capture_output=True, timeout=600)
src = subprocess.run([str(PY), "-m", "modcheck", "--config-dir", str(cfg), "check",
                      "--profile", "s", "--mc", "26.3", "--loader", "fabric", "--no-color"],
                     cwd=str(ROOT), env=dict(env, PYTHONPATH=str(ROOT / "src")),
                     capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
pack = run("onefile-check", [str(one), "--config-dir", str(cfg), "check",
                             "--profile", "s", "--mc", "26.3", "--loader", "fabric", "--no-color"])
src_sum = next((l.strip() for l in src.stdout.splitlines() if l.startswith("汇总")), "")
pkg_sum = next((l.strip() for l in pack.stdout.splitlines() if l.startswith("汇总")), "")
print("    源码版:", src_sum)
print("    打包版:", pkg_sum)
print("    逐字一致:", "✅" if src_sum and src_sum == pkg_sum else "❌")
print("    退出码:", src.returncode, "vs", pack.returncode,
      "✅" if src.returncode == pack.returncode else "❌")

print("=== 3) CLI 单文件：菜单是否有下载入口 [5] ===")
menu = subprocess.run([str(one), "--config-dir", str(cfg)], input="0\n",
                      capture_output=True, text=True, encoding="utf-8",
                      errors="replace", timeout=120, env=env)
hit = [l.strip() for l in menu.stdout.splitlines() if "下载" in l]
print("    找到下载相关行:", hit[:2] if hit else "❌ 没找到")

print("=== 4) CLI 免安装目录 ===")
stand = ROOT / "dist-standalone" / "modcheck" / "modcheck.exe"
p2 = run("standalone", [str(stand), "--version"])
print("   ", p2.stdout.strip() or p2.stderr.strip()[:120])

print("=== 5) GUI：启动后是否存活 ===")
gui = ROOT / "dist-gui" / "modcheck-gui" / "modcheck-gui.exe"
proc = subprocess.Popen([str(gui)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
deadline = time.time() + 12
while time.time() < deadline and proc.poll() is None:
    time.sleep(0.4)
if proc.poll() is None:
    print("    ✅ 存活（窗口已显示）")
    proc.kill(); proc.wait()
else:
    print(f"    ❌ 已退出 exit={proc.returncode}")
