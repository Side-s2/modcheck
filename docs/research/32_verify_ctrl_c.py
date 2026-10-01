# -*- coding: utf-8 -*-
"""验证 Ctrl+C 中断语义（PRD D11）：
   · 检查进行中中断 -> 输出已完成部分的简版摘要，不打印 traceback
   · 退出码 130
Windows 上用 CREATE_NEW_PROCESS_GROUP + CTRL_BREAK_EVENT 模拟。
"""
import os, signal, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
PY = ROOT / ".toolchain" / "Python311" / "python.exe"
cfg = Path(tempfile.mkdtemp(prefix="sigint-"))
env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8", NO_COLOR="1")

subprocess.run([str(PY), "-m", "modcheck", "--config-dir", str(cfg), "scan", str(ROOT/"mods_sample"),
                "--profile", "s", "--yes"], cwd=str(ROOT), env=env, capture_output=True)

for label, extra in [("检查进行中（30 模组 --refresh）", ["--refresh"])]:
    p = subprocess.Popen(
        [str(PY), "-m", "modcheck", "--config-dir", str(cfg), "check", "--profile", "s",
         "--mc", "26.3", "--loader", "fabric", "--no-color", *extra],
        cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    time.sleep(6)                      # 让它跑起来
    print(f"--- {label} ---")
    print(f"    发送 CTRL_BREAK_EVENT ...", flush=True)
    try:
        p.send_signal(signal.CTRL_BREAK_EVENT)
    except Exception as e:
        print(f"    发送失败: {e}")
    try:
        out, err = p.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        p.kill(); out, err = p.communicate()
        print("    ⚠ 30 秒内没有响应中断，已强杀")
    print(f"    exit = {p.returncode}   （PRD 期望 130）")
    tb = "Traceback" in (out + err)
    print(f"    含 Traceback: {tb}   （必须为 False）")
    tail = [l for l in out.splitlines() if l.strip()][-6:]
    print("    输出尾部：")
    for l in tail:
        print("      |" + l[:100])
    if err.strip():
        print("    stderr 尾部：")
        for l in err.strip().splitlines()[-3:]:
            print("      |" + l[:100])

import shutil; shutil.rmtree(cfg, ignore_errors=True)
