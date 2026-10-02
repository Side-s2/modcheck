# -*- coding: utf-8 -*-
"""从作者提供的 icon.png 生成多尺寸 ICO（零第三方依赖，只用 PyQt6 做缩放）。

输入：工作区根目录的 icon.png（作者提供，任意尺寸/比例）
输出：assets/modcheck.ico（6 个尺寸）+ assets/icon-{n}.png（便于预览与复用）

两种处理方式都在这里做了：
  · **非正方形** -> 用透明边距补成正方形（不裁切，避免切掉画面边缘的图案）
  · **缩放到小尺寸** -> 用 Qt 的平滑变换（SmoothTransformation），
    比默认的快速缩放干净得多（小图标上尤其明显）
"""
import os, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPainter

SRC = ROOT / "icon.png"
OUT = ROOT / "assets"
OUT.mkdir(exist_ok=True)

if not SRC.is_file():
    raise SystemExit(f"找不到源图：{SRC}")

src = QImage(str(SRC))
if src.isNull():
    raise SystemExit(f"读不了这张图：{SRC}")
print(f"源图 {src.width()}x{src.height()}")

# --- 1) 补成正方形（透明边距，居中）---
side = max(src.width(), src.height())
# 四周再留 4% 边距：Windows 的小图标在任务栏/资源管理器里贴边会显得很挤
margin = int(side * 0.04)
canvas_side = side + margin * 2
canvas = QImage(canvas_side, canvas_side, QImage.Format.Format_ARGB32)
canvas.fill(QColor(0, 0, 0, 0))
p = QPainter(canvas)
p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
p.drawImage((canvas_side - src.width()) // 2, (canvas_side - src.height()) // 2, src)
p.end()
print(f"补成正方形 {canvas_side}x{canvas_side}（留白 {margin}px）")


def at_size(n: int) -> QImage:
    return canvas.scaled(n, n, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)


SIZES = (256, 128, 64, 48, 32, 16)
pngs = []
for s in SIZES:
    img = at_size(s)
    path = OUT / f"icon-{s}.png"
    img.save(str(path), "PNG")
    pngs.append((s, path.read_bytes()))
    print(f"  生成 {s}x{s}")

# --- 2) 手工封 ICO（内嵌 PNG，Vista+ 支持）---
header = struct.pack("<HHH", 0, 1, len(pngs))
offset = 6 + 16 * len(pngs)
entries, blobs = b"", b""
for size, data in pngs:
    dim = 0 if size >= 256 else size
    entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
    blobs += data
    offset += len(data)
ico = OUT / "modcheck.ico"
ico.write_bytes(header + entries + blobs)

# 素材也留一份进 assets，方便以后重新生成
(OUT / "icon-source.png").write_bytes(SRC.read_bytes())
print(f"\n图标已写入 {ico.relative_to(ROOT)}（{len(ico.read_bytes())} 字节，{len(pngs)} 个尺寸）")
