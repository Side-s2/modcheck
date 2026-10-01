# -*- coding: utf-8 -*-
"""渲染扫描对话框供视觉评审。"""
import os, sys, tempfile
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))
os.environ["QT_QPA_PLATFORM"] = "windows"
from PyQt6.QtWidgets import QApplication
from modcheck.gui import theme
from modcheck.gui.backend import CliBackend
from modcheck.gui.scan_dialog import ScanDialog
cfg = Path(tempfile.mkdtemp(prefix="scan-"))
app = QApplication(sys.argv); app.setStyle("Fusion"); app.setStyleSheet(theme.QSS)
d = ScanDialog(CliBackend(config_dir=cfg))
d.list.addItem(str(ROOT / "mods_sample"))
d.list.addItem(str(ROOT / "mods_sample" / "sub"))
d.lb_progress.setText("正在读取 12/30：carpet-extra-26.1.jar")
d.bar.setRange(0, 30); d.bar.setValue(12)
d.show()
for _ in range(5): app.processEvents()
d.grab().save(str(ROOT / "docs" / "design" / "gui_scan.png"))
d.hide(); print("已渲染 gui_scan.png")
