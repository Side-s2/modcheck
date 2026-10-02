# -*- coding: utf-8 -*-
"""把下拉框弹层单独截出来看那个"多余的直角外框"。"""
import os, sys
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))
os.environ["QT_QPA_PLATFORM"] = "windows"
from PyQt6.QtWidgets import QApplication, QComboBox
from modcheck.gui import theme
app = QApplication(sys.argv); app.setStyle("Fusion"); app.setStyleSheet(theme.QSS)
cb = QComboBox()
cb.addItems(["26.3（最新正式版）", "26.2", "26.1.2", "26.1", "26.0"])
cb.resize(240, 34)
theme.style_combo_popup(cb)
cb.show()
for _ in range(4): app.processEvents()
cb.showPopup()
for _ in range(6): app.processEvents()
view = cb.view()
container = view.window()
print("view 类:", type(view).__name__, "| 容器类:", type(container).__name__)
print("容器 frameShape:", container.frameShape(), "frameWidth:", container.frameWidth())
# 把弹层容器连同列表一起截下来
container.grab().save(str(ROOT / "docs" / "design" / "combo_popup.png"))
print("已渲染 combo_popup.png，尺寸:", container.size().width(), "x", container.size().height())
cb.hidePopup()
