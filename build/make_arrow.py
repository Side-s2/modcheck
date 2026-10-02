# -*- coding: utf-8 -*-
"""生成下拉箭头图（很小的灰色三角，透明底）。

为什么要图：给 QComboBox 设了 QSS 边框后，Qt 就**不再画原生箭头**，
而 ::down-arrow 只接受图片（image: url(...)），用 border 假冒三角会被渲染成实心方块。
"""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPolygonF

OUT = ROOT / "assets"
OUT.mkdir(exist_ok=True)
for name, color, w, h in (("arrow-down.png", "#6B7280", 20, 12),
                          ("arrow-down-on.png", "#2F6FED", 20, 12)):
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawPolygon(QPolygonF([QPointF(1, 3), QPointF(w - 1, 3), QPointF(w / 2, h - 1)]))
    p.end()
    img.save(str(OUT / name), "PNG")
    print("已生成", name)
