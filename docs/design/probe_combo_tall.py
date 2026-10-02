# -*- coding: utf-8 -*-
"""在 setUniformItemSizes 基础上，把行高调到舒服的值。"""
import os, sys
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))
os.environ["QT_QPA_PLATFORM"] = "windows"
from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QApplication, QComboBox
from modcheck.gui import theme
app = QApplication(sys.argv); app.setStyle("Fusion"); app.setStyleSheet(theme.QSS)
ITEMS = ["26.3", "26.2", "26.1.2", "26.1", "26.0"]

def measure(build, label):
    cb = QComboBox(); cb.resize(240, 34); build(cb); cb.addItems(ITEMS)
    cb.show()
    for _ in range(3): app.processEvents()
    cb.showPopup()
    for _ in range(6): app.processEvents()
    v = cb.view()
    rects = [v.visualRect(v.model().index(i, 0)) for i in range(v.model().rowCount())]
    step = rects[1].top() - rects[0].top()
    gap = rects[1].top() - rects[0].bottom()
    print(f"  {label:44s} 高度={rects[0].height():3d} 步进={step:3d} 间距={gap:3d} "
          + ("✅" if gap >= 0 else "❌"))
    cb.hidePopup()

def base(cb):
    theme.style_combo_popup(cb)
    cb.view().setUniformItemSizes(True)

measure(base, "A) uniform 现状")
measure(lambda cb: (base(cb), cb.view().setStyleSheet(
    cb.view().styleSheet() + "QListView::item{padding:8px 10px;}")), "B) uniform + item padding 8px")

class Tall(theme._PopupItemDelegate):
    def sizeHint(self, option, index):
        return QSize(super().sizeHint(option, index).width(), 30)
measure(lambda cb: (theme.style_combo_popup(cb), cb.view().setUniformItemSizes(True),
                    cb.view().setItemDelegate(Tall(cb.view())), cb.view().reset()),
        "C) uniform + 代理返回 30px")
