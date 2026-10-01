# -*- coding: utf-8 -*-
"""渲染下载对话框供视觉评审（用你服务器的真实检查数据）。"""
import os, sys, tempfile
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))
os.environ["QT_QPA_PLATFORM"] = "windows"
from PyQt6.QtWidgets import QApplication, QCheckBox, QTableWidgetItem
from modcheck.gui import theme
from modcheck.gui.backend import CliBackend
from modcheck.gui.download_dialog import DownloadDialog

# 用假 prep 造一份逼真的展示数据（不联网、不写盘）
class FakeFile:
    def __init__(self, name, size): self.filename, self.size = name, size
class FakeVersion:
    def __init__(self, v): self.version_number = v
class FakeEntry:
    def __init__(self, n): self.display_name, self.file_name, self.key = n, n + ".jar", n
class FakeItem:
    def __init__(self, n, v, f, size):
        self.entry, self.version, self.file = FakeEntry(n), FakeVersion(v), FakeFile(f, size)
        self.target = Path("x")
class FakePlan:
    def __init__(self, items): self.items = tuple(items)
class FakePrep:
    def __init__(self):
        self.plan = FakePlan([
            FakeItem("ImmediatelyFast", "1.17.1+26.3", "ImmediatelyFast-1.17.1+26.3-fabric.jar", 480000),
            FakeItem("Carpet Extra Extras", "26.3-1.4.2", "carpet-extra-extras-26.3-1.4.2.jar", 210000),
            FakeItem("MagicLib", "v0.8.882-mc26.3-fabric", "magiclib-v0.8.882-mc26.3-fabric.jar", 1500000),
            FakeItem("Carpet Org Addition", "1.46.0", "carpet-org-addition-1.46.0.jar", 3300000),
        ])
        self.target_dir = Path("D:/mods-new")
        self.conflicts = (self.plan.items[2],)
        self.extra_files = 2
        self.no_jar = (1,)
        self.no_version = ()

cfg = Path(tempfile.mkdtemp(prefix="dlg-"))
app = QApplication(sys.argv); app.setStyle("Fusion"); app.setStyleSheet(theme.QSS)
d = DownloadDialog(CliBackend(config_dir=cfg), report=None)
d._prep = FakePrep(); d.ed_dir.setText("D:/mods-new"); d._fill()
d.show()
for _ in range(5): app.processEvents()
d.grab().save(str(ROOT / "docs" / "design" / "gui_download.png"))
d.hide(); print("已渲染 gui_download.png")
