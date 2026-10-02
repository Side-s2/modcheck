# -*- coding: utf-8 -*-
"""找出真正能让行高与布局步进一致的做法。"""
import os, sys
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))
os.environ["QT_QPA_PLATFORM"] = "windows"
from PyQt6.QtWidgets import QApplication, QComboBox
from modcheck.gui import theme
app = QApplication(sys.argv); app.setStyle("Fusion"); app.setStyleSheet(theme.QSS)
ITEMS = ["26.3", "26.2", "26.1.2", "26.1", "26.0"]

def measure(build, label):
    cb = QComboBox(); cb.resize(240, 34)
    build(cb)
    cb.addItems(ITEMS)
    cb.show()
    for _ in range(3): app.processEvents()
    cb.showPopup()
    for _ in range(6): app.processEvents()
    v = cb.view()
    rects = [v.visualRect(v.model().index(i, 0)) for i in range(v.model().rowCount())]
    step = rects[1].top() - rects[0].top() if len(rects) > 1 else 0
    gap = rects[1].top() - rects[0].bottom() if len(rects) > 1 else 0
    print(f"  {label:38s} 高度={rects[0].height():3d} 步进={step:3d} 间距={gap:4d} "
          + ("✅" if gap >= 0 else "❌ 重叠"))
    cb.hidePopup()

measure(lambda cb: theme.style_combo_popup(cb), "1) 现状（仅设代理）")
measure(lambda cb: (theme.style_combo_popup(cb), cb.view().reset()), "2) 设完代理再 view.reset()")
measure(lambda cb: (theme.style_combo_popup(cb), cb.view().setSpacing(0)), "3) 显式 setSpacing(0)")
measure(lambda cb: (theme.style_combo_popup(cb), cb.view().reset(), cb.view().setSpacing(0)), "4) reset + setSpacing(0)")
measure(lambda cb: (theme.style_combo_popup(cb), cb.view().setUniformItemSizes(True), cb.view().reset()),
        "5) setUniformItemSizes(True) + reset")
def no_sizehint(cb):
    theme.style_combo_popup(cb)
    cb.view().setItemDelegate(theme._PopupItemDelegate(cb.view()))
    cb.view().reset()
measure(no_sizehint, "6) 重设代理 + reset")
