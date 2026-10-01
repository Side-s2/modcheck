# -*- coding: utf-8 -*-
"""实测两个 bug：设置能否改默认版本 + 扫描第二阶段到底要多久。"""
import os, sys, time, tempfile
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
cfg = Path(tempfile.mkdtemp(prefix="bugfix-"))
from modcheck.gui.backend import CliBackend
be = CliBackend(config_dir=cfg)

print("=== Bug 2：设置里改默认 MC 版本 ===")
from modcheck.gui.settings_dialog import SettingsDialog
from modcheck.core.models import Loader
dlg = SettingsDialog(be)
dlg.ed_mc.setText("26.3")
try:
    s = dlg._collect()
    print("  ✅ 改默认版本成功 ->", s.default_mc_version)
except Exception as exc:
    print("  ❌ 仍然失败:", type(exc).__name__, exc)
try:
    dlg.ed_mc.setText("99.99")
    bad = dlg._collect()
    print("  ⚠ 非法版本没被拦住:", bad.default_mc_version)
except Exception as exc:
    print("  ✅ 非法版本被正确拦住:", str(exc)[:80])

print()
print("=== Bug 1：扫描的两阶段耗时 ===")
events = []
t0 = time.time()
def prog(done, total, name):
    events.append((round(time.time() - t0, 1), done, total, name[:28]))
report = be.scan([ROOT / "mods_sample"], on_progress=prog)
t1 = time.time()
print(f"  回调次数: {len(events)}")
if events:
    print(f"  最后一次 jar 回调: t={events[-1][0]}s  ({events[-1][1]}/{events[-1][2]})")
print(f"  扫描总耗时: {t1 - t0:.1f}s  -> 读完 jar 之后又花了 {t1 - t0 - (events[-1][0] if events else 0):.1f}s")
print(f"  识别出 {len(report.entries)} 个模组（指纹 {report.by_hash} / jar信息 {report.by_meta} / 搜索 {report.by_search}）")
print()
print("  这就是用户看到的「卡在最后一个 mod」：")
print(f"  进度条停在 100% 之后，程序还在联网搜索 {t1 - t0 - (events[-1][0] if events else 0):.0f} 秒，且期间没有任何反馈。")
