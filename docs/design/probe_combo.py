# -*- coding: utf-8 -*-
"""定位选中项那个方框到底是谁画的：三种候选各渲一张。"""
import os, sys
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))
os.environ["QT_QPA_PLATFORM"] = "windows"
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QComboBox, QListView
from modcheck.gui import theme
app = QApplication(sys.argv); app.setStyle("Fusion"); app.setStyleSheet(theme.QSS)

def shot(cb, name):
    cb.show()
    for _ in range(3): app.processEvents()
    cb.showPopup()
    for _ in range(5): app.processEvents()
    cb.view().window().grab().save(str(ROOT / "docs" / "design" / f"combo_{name}.png"))
    cb.hidePopup()
    print("  已渲染", name)

def make():
    cb = QComboBox(); cb.addItems(["26.3（最新正式版）", "26.2", "26.1.2", "26.1"])
    cb.resize(240, 34); theme.style_combo_popup(cb); return cb

# A：现状
shot(make(), "A_now")
# B：视图不接收焦点（去掉焦点框）
cb = make(); cb.view().setFocusPolicy(Qt.FocusPolicy.NoFocus)
cb.view().setSelectionRectVisible(False)
shot(cb, "B_nofocus")
# C：彻底不用默认画法 —— 视图自绘选中底色、去掉所有边框
cb = make()
v = cb.view()
v.setStyleSheet(
    "QListView { border: 0px; outline: 0px; background: transparent; }"
    "QListView::item { border: 0px; padding: 6px 10px; }"
    "QListView::item:selected { border: 0px; background: #EAF0FE; }"
    "QListView::item:focus { border: 0px; outline: 0px; }")
v.setFocusPolicy(Qt.FocusPolicy.NoFocus)
shot(cb, "C_clean")
