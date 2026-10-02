# -*- coding: utf-8 -*-
"""复现：目标目录里**已存在同名文件**时下载会怎样。"""
import sys, tempfile, time
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))
cfg = Path(tempfile.mkdtemp(prefix="dlc-"))
target = Path(tempfile.mkdtemp(prefix="dlt-"))
from modcheck.gui.backend import CliBackend
be = CliBackend(config_dir=cfg)
be.save_scan(be.scan([ROOT / "mods_sample"]), "s")
be.run("s", "26.3", "Fabric", lambda *a: None, lambda: False)

prep = be.prepare_download(be.last_report, target)
items = list(prep.plan.items)
print(f"计划下载 {len(items)} 个")

# ★ 关键：先把同名文件都"占住"，模拟用户的 mods 文件夹
for it in items:
    it.target.write_bytes(b"x" * 1000)
print(f"已在目标目录放好 {len(items)} 个同名文件（模拟'下载到正在用的 mods 文件夹'）")

# 情形 A：不覆盖（GUI 默认）
print("\n--- 情形 A：全部选'不覆盖'（GUI 默认）---")
t0 = time.time()
ow = {it.target.name: False for it in items}
out = be.run_download(prep, overwrite=ow, on_progress=lambda d, t, n: None, should_stop=lambda: False)
s = out.summary
print(f"  耗时 {time.time()-t0:.1f}s  成功 {s.ok} / 跳过 {s.skipped_total} / 失败 {s.failed}")
for row in s.failure_rows[:3]: print("   失败:", row)

# 情形 B：覆盖
print("\n--- 情形 B：全部覆盖 ---")
t0 = time.time()
ow2 = {it.target.name: True for it in items}
out2 = be.run_download(prep, overwrite=ow2, on_progress=lambda d, t, n: None, should_stop=lambda: False)
s2 = out2.summary
print(f"  耗时 {time.time()-t0:.1f}s  成功 {s2.ok} / 跳过 {s2.skipped_total} / 失败 {s2.failed}")
for row in s2.failure_rows[:3]: print("   失败:", row)
