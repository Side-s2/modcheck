# -*- coding: utf-8 -*-
"""渲染使用教程窗口供视觉评审。"""
import os, sys
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))
os.environ["QT_QPA_PLATFORM"] = "windows"
from PyQt6.QtWidgets import QApplication
from modcheck.gui import theme
from modcheck.gui.tutorial_dialog import TutorialDialog
app = QApplication(sys.argv); app.setStyle("Fusion"); app.setStyleSheet(theme.QSS)
d = TutorialDialog(); d.resize(1000, 700)
d.show()
for _ in range(6): app.processEvents()
d.grab().save(str(ROOT / "docs" / "design" / "gui_tutorial.png"))
print("已渲染 gui_tutorial.png")
print("目录前 3 项:", [d.list.item(i).text() for i in range(min(3, d.list.count()))])
d.hide()
