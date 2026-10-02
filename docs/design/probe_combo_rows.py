# -*- coding: utf-8 -*-
"""量化验证：下拉各行是否**纵向重叠**（不靠肉眼）。"""
import os, sys
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))
os.environ["QT_QPA_PLATFORM"] = "windows"
from PyQt6.QtWidgets import QApplication, QComboBox
from modcheck.gui import theme
app = QApplication(sys.argv); app.setStyle("Fusion"); app.setStyleSheet(theme.QSS)

def rows(cb, label):
    cb.show()
    for _ in range(3): app.processEvents()
    cb.showPopup()
    for _ in range(5): app.processEvents()
    v = cb.view()
    rects = [v.visualRect(v.model().index(i, 0)) for i in range(v.model().rowCount())]
    heights = [r.height() for r in rects]
    gaps = [rects[i+1].top() - rects[i].bottom() for i in range(len(rects)-1)]
    h = v.sizeHintForRow(0)
    ok = all(g >= 0 for g in gaps) and h >= 20
    print(f"  {label}: 行高={heights[:3]}... sizeHintForRow={h} 行间距={gaps[:4]} ->",
          "✅ 不重叠" if ok else "❌ 重叠/过矮")
    cb.hidePopup()
    return ok

# 情形 A：先 addItems 再 style（这正是当前代码的顺序）
cb1 = QComboBox(); cb1.addItems(["26.3","26.2","26.1.2","26.1","26.0"]); cb1.resize(240,34)
theme.style_combo_popup(cb1)
a = rows(cb1, "A 先加条目后设代理（当前顺序）")

# 情形 B：先设代理再 addItems
cb2 = QComboBox(); cb2.resize(240,34); theme.style_combo_popup(cb2)
cb2.addItems(["26.3","26.2","26.1.2","26.1","26.0"])
b = rows(cb2, "B 先设代理后加条目")

print()
print("结论：", "顺序确实是原因 ✅" if (b and not a) else ("两者都不重叠（顺序不是原因）" if (a and b) else "两者都重叠"))
