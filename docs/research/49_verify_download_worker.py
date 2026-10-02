# -*- coding: utf-8 -*-
"""验证下载修复：走真实的 DownloadWorker 回调路径（这才是之前炸掉的地方）。"""
import os, sys, tempfile, time
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))
os.environ["QT_QPA_PLATFORM"] = "windows"
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QEventLoop
app = QApplication(sys.argv)

cfg = Path(tempfile.mkdtemp(prefix="dlw-"))
target = Path(tempfile.mkdtemp(prefix="dlt-"))
from modcheck.gui.backend import CliBackend
from modcheck.gui.download_dialog import DownloadWorker
be = CliBackend(config_dir=cfg)
be.save_scan(be.scan([ROOT / "mods_sample"]), "s")
be.run("s", "26.3", "Fabric", lambda *a: None, lambda: False)
prep = be.prepare_download(be.last_report, target)
print(f"计划下载 {len(prep.plan.items)} 个")

events = []
outcome = {}
w = DownloadWorker(be, prep, {})
w.progressed.connect(lambda d, t, n: events.append((d, t, n)))
w.done.connect(lambda o: outcome.update(ok=o))
w.failed.connect(lambda m: outcome.update(err=m))
loop = QEventLoop()
w.finished.connect(loop.quit)
t0 = time.time()
w.start()
loop.exec()
print(f"耗时 {time.time()-t0:.1f}s")

if "err" in outcome:
    print("❌ Worker 报错:", outcome["err"][:200])
else:
    s = outcome["ok"].summary
    print(f"✅ 成功 {s.ok} / 跳过 {s.skipped_total} / 失败 {s.failed}")
    print(f"   进度回调 {len(events)} 次，前 3 次: {events[:3]}")
    print(f"   目标目录实有文件: {len(list(target.glob('*.jar')))} 个")
    if s.failure_rows:
        print("   失败原因:", s.failure_rows[0])
