# -*- coding: utf-8 -*-
"""对比：自绘代理 vs 纯样式表 vs 完全不干预。"""
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
    cb = QComboBox(); cb.resize(240, 34); build(cb); cb.addItems(ITEMS)
    cb.show()
    for _ in range(3): app.processEvents()
    cb.showPopup()
    for _ in range(6): app.processEvents()
    v = cb.view()
    rects = [v.visualRect(v.model().index(i, 0)) for i in range(v.model().rowCount())]
    step = rects[1].top() - rects[0].top()
    gap = rects[1].top() - rects[0].bottom()
    print(f"  {label:40s} 高度={rects[0].height():3d} 步进={step:3d} 间距={gap:3d} "
          + ("✅ 不重叠" if gap >= 0 else "❌ 重叠"))
    cb.hidePopup()

measure(lambda cb: theme.style_combo_popup(cb), "1) 自绘代理（现状）")
measure(lambda cb: (theme.style_combo_popup(cb), cb.view().setUniformItemSizes(True)),
        "2) 自绘代理 + uniform")
measure(lambda cb: None, "3) 完全不干预（原生）")
def qss_only(cb):
    v = cb.view()
    v.setStyleSheet("QListView{background:#fff;border:1px solid #E4E7EC;border-radius:8px;padding:4px;}"
                    "QListView::item{padding:8px 10px;border:none;border-radius:6px;}"
                    "QListView::item:selected{background:#EAF0FE;}")
measure(qss_only, "4) 只用样式表（无代理）")
measure(lambda cb: (cb.view().setUniformItemSizes(True)), "5) 原生 + uniform")
