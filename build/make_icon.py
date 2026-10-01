# -*- coding: utf-8 -*-
"""生成程序图标：用 Qt 画一个圆角方块 + 对勾，存 PNG，再手工封成多尺寸 ICO。

为什么不引第三方库：本项目零运行时依赖，图标生成是**开发期一次性**的事，
用已经装好的 PyQt6 画图即可，不需要 Pillow 之类。
ICO 格式很简单：6 字节头 + 每张图 16 字节目录项 + 图像数据（可以直接内嵌 PNG）。
"""
import os, struct, sys
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPen

ACCENT = "#2F6FED"
OUT = ROOT / "assets"
OUT.mkdir(exist_ok=True)


def draw(size: int) -> QImage:
    """画一张 size×size 的图标：圆角蓝底 + 白色对勾。"""
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    # 圆角底
    path = QPainterPath()
    r = size * 0.22
    path.addRoundedRect(QRectF(size * 0.04, size * 0.04, size * 0.92, size * 0.92), r, r)
    p.fillPath(path, QBrush(QColor(ACCENT)))
    # 对勾（用折线画，比字体符号在不同 DPI 下更稳定）
    pen = QPen(QColor("white"))
    pen.setWidthF(size * 0.11)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawPolyline([
        __import__("PyQt6.QtCore", fromlist=["QPointF"]).QPointF(size * 0.27, size * 0.52),
        __import__("PyQt6.QtCore", fromlist=["QPointF"]).QPointF(size * 0.44, size * 0.69),
        __import__("PyQt6.QtCore", fromlist=["QPointF"]).QPointF(size * 0.75, size * 0.33),
    ])
    p.end()
    return img


def to_png(img: QImage, path: Path) -> bytes:
    img.save(str(path), "PNG")
    return path.read_bytes()


SIZES = (256, 128, 64, 48, 32, 16)
pngs = []
for s in SIZES:
    pngs.append((s, to_png(draw(s), OUT / f"icon-{s}.png")))
    print(f"  画出 {s}x{s}")

# --- 手工封 ICO（内嵌 PNG，Vista+ 支持）---
header = struct.pack("<HHH", 0, 1, len(pngs))          # reserved, type=icon, count
offset = 6 + 16 * len(pngs)
entries, blobs = b"", b""
for size, data in pngs:
    dim = 0 if size >= 256 else size                    # ICO 里 256 记作 0
    entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
    blobs += data
    offset += len(data)
ico = OUT / "modcheck.ico"
ico.write_bytes(header + entries + blobs)
print(f"\n图标已写入 {ico.relative_to(ROOT)}（{len(ico.read_bytes())} 字节，{len(pngs)} 个尺寸）")
