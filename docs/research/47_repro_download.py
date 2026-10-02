# -*- coding: utf-8 -*-
"""复现下载失败：看每条到底为什么失败。"""
import sys, tempfile
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))
cfg = Path(tempfile.mkdtemp(prefix="dl-"))
target = Path(tempfile.mkdtemp(prefix="dltarget-"))
from modcheck.gui.backend import CliBackend
be = CliBackend(config_dir=cfg)

# 1) 先确认设置能保存了
s = be.load_settings()
s.default_mc_version = "26.3"
be.save_settings(s)
print("设置保存:", "✅ 成功" if be.load_settings().default_mc_version == "26.3" else "❌ 失败")

# 2) 建清单 + 检查，再下载
be.save_scan(be.scan([ROOT / "mods_sample"]), "s")
verdict, rows = be.run("s", "26.3", "Fabric", lambda *a: None, lambda: False)
print("检查:", verdict[:40])

prep = be.prepare_download(be.last_report, target)
print(f"\n可下载 {len(prep.plan.items)} 个，跳过 {len(prep.plan.skipped)} 个，无 jar {len(prep.no_jar)}，无版本 {len(prep.no_version)}")
if prep.plan.items:
    it = prep.plan.items[0]
    print(f"第一个: {it.file.filename}")
    print(f"  下载地址: {str(it.file.url)[:90]}")
    print(f"  期望 sha1: {it.file.hashes.get('sha1')}")
    print(f"  文件大小: {it.file.size}")

print("\n开始下载（前 3 个）……")
out = be.run_download(prep, on_progress=lambda d, t, n: None, should_stop=lambda: False)
s2 = out.summary
print(f"  成功 {s2.ok} / 跳过 {s2.skipped_total} / 失败 {s2.failed}")
if s2.failure_rows:
    print("  失败原因（前 5 条）:")
    for row in s2.failure_rows[:5]:
        print("   ", row)
print(f"  目标目录里剩下什么: {[p.name for p in target.iterdir()][:5]}")
print(f"  有 .part 残留吗: {[p.name for p in target.glob('*.part')][:5]}")
