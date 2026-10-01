# -*- coding: utf-8 -*-
"""GUI 样式草稿：把主窗口渲染成 PNG，用于视觉评审（不参与正式构建）。"""
import os, sys
# offscreen 平台找不到字体（文字渲成方框），所以用真实 windows 平台；
# grab() 对**未显示**的控件同样有效 —— 不会在桌面上弹窗打扰用户。
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout, QLabel,
                             QProgressBar, QPushButton, QTabWidget, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView)

BG, CARD, BORDER = "#F4F5F7", "#FFFFFF", "#E4E7EC"
TEXT, MUTED, ACCENT = "#1A1D21", "#6B7280", "#2F6FED"
RED, ORANGE, YELLOW, GRAY, GREEN = "#E5484D", "#F76B15", "#F5A524", "#8B8D98", "#30A46C"

QSS = f"""
* {{ font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; font-size: 13px; color: {TEXT}; }}
QWidget#root {{ background: {BG}; }}
QFrame#card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px; }}
QLabel#title {{ font-size: 17px; font-weight: 600; }}
QLabel#sub {{ color: {MUTED}; font-size: 12px; }}
QLabel#verdict {{ font-size: 15px; font-weight: 600; padding: 4px 14px; }}
QComboBox {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px;
             padding: 7px 12px; min-width: 150px; }}
QComboBox:hover {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QPushButton#primary {{ background: {ACCENT}; color: white; border: none; border-radius: 8px;
                       padding: 9px 22px; font-weight: 600; }}
QPushButton#primary:hover {{ background: #2A62D4; }}
QPushButton {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px; padding: 9px 16px; }}
QPushButton:hover {{ border-color: #C7CCD4; }}
QProgressBar {{ border: none; border-radius: 4px; background: #E9ECF1; height: 8px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QTabBar::tab {{ background: transparent; padding: 8px 14px; margin-right: 4px;
                border-radius: 8px; color: {MUTED}; }}
QTabBar::tab:selected {{ background: #EAF0FE; color: {ACCENT}; font-weight: 600; }}
QTableWidget {{ border: none; gridline-color: transparent; background: {CARD}; }}
QTableWidget::item {{ padding: 10px 8px; border-bottom: 1px solid #F0F2F5; }}
QTableWidget::item:selected {{ background: #EAF0FE; color: {TEXT}; }}
QHeaderView::section {{ background: {CARD}; border: none; border-bottom: 1px solid {BORDER};
                        padding: 10px 8px; color: {MUTED}; font-weight: 600;
                        text-align: left; }}
QTableWidget {{ selection-background-color: #EAF0FE; }}
"""

def chip(text, color):
    lb = QLabel(text)
    lb.setStyleSheet(f"color:{color}; font-weight:600; background:transparent;")
    return lb

app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(QSS)

root = QWidget(); root.setObjectName("root")
outer = QVBoxLayout(root); outer.setContentsMargins(18, 18, 18, 18); outer.setSpacing(14)

# ---- 顶部：标题 + 控制条 ----
head = QFrame(); head.setObjectName("card")
hl = QVBoxLayout(head); hl.setContentsMargins(18, 16, 18, 16); hl.setSpacing(12)
t1 = QLabel("Minecraft 模组兼容性检查"); t1.setObjectName("title")
t2 = QLabel("检查你的模组是否支持目标游戏版本 —— 数据来自 Modrinth"); t2.setObjectName("sub")
hl.addWidget(t1); hl.addWidget(t2)

row = QHBoxLayout(); row.setSpacing(10)
for label, items in (("模组清单", ["服务器A（30 个模组）"]),
                     ("目标版本", ["26.3（最新正式版）", "26.2", "26.1"]),
                     ("服务端加载器", ["Fabric", "NeoForge", "Forge"])):
    box = QVBoxLayout(); box.setSpacing(5)
    cap = QLabel(label); cap.setObjectName("sub")
    cb = QComboBox(); cb.addItems(items)
    box.addWidget(cap); box.addWidget(cb)
    row.addLayout(box)
row.addStretch(1)
go = QPushButton("开始检查"); go.setObjectName("primary")
row.addWidget(go, alignment=Qt.AlignmentFlag.AlignBottom)
hl.addLayout(row)

prog = QVBoxLayout(); prog.setSpacing(6)
pl = QHBoxLayout()
pl.addWidget(QLabel("正在检查 12/30：carpet-extra-26.1.jar")); pl.addStretch(1)
pl.addWidget(QLabel("已用 8 秒 · 预计还需 12 秒"))
prog.addLayout(pl)
bar = QProgressBar(); bar.setRange(0, 30); bar.setValue(12); bar.setTextVisible(False)
prog.addWidget(bar)
hl.addLayout(prog)
outer.addWidget(head)

# ---- 结论条 ----
verdict = QFrame(); verdict.setObjectName("card")
vl = QHBoxLayout(verdict); vl.setContentsMargins(4, 4, 4, 4)
v = QLabel("❌  现在还不能升级到 Minecraft 26.3 —— 30 个模组中有 2 个阻塞、0 个未判定")
v.setObjectName("verdict"); v.setStyleSheet(f"color:{RED};")
vl.addWidget(v); outer.addWidget(verdict)

# ---- 分页签 + 表格 ----
body = QFrame(); body.setObjectName("card")
bl = QVBoxLayout(body); bl.setContentsMargins(14, 12, 14, 14); bl.setSpacing(10)
tabs = QTabWidget(); tabs.setDocumentMode(True)
ROWS = {
    "全部 30": [("Antideath-Carpet-Add…", RED, "阻塞", "v1.4.7-mc26.1 → v1.5.1", "2026-08-10"),
                ("Carpet Extra", RED, "阻塞", "26.1 → 26.2", "2026-06-21"),
                ("ScalableLux", ORANGE, "仅存测试版", "0.2.0 → 0.2.1", "2026-06-12"),
                ("MagicLib", YELLOW, "需注意", "v0.8.838 → v0.8.882", "2026-09-27"),
                ("ImmediatelyFast", GREEN, "就绪", "1.15.2 → 1.17.1", "2026-09-17")],
    "● 阻塞 2": [], "● 仅存测试版 4": [], "● 需注意 3": [], "● 未判定 0": [], "● 就绪 21": [],
}
# 页签带状态名：只有色点+数字时，用户不点进去就不知道是什么状态
order = ["全部 30", "● 阻塞 2", "● 仅存测试版 4", "● 需注意 3", "● 未判定 0", "● 就绪 21"]
TAB_COLOR = {"● 阻塞 2": RED, "● 仅存测试版 4": ORANGE, "● 需注意 3": YELLOW,
             "● 未判定 0": GRAY, "● 就绪 21": GREEN}
for name in order:
    page = QWidget(); pl2 = QVBoxLayout(page); pl2.setContentsMargins(0, 8, 0, 0)
    tbl = QTableWidget(len(ROWS[name]), 4)
    tbl.setHorizontalHeaderLabels(["模组", "状态", "版本", "发布日期"])
    tbl.verticalHeader().setVisible(False)
    tbl.setShowGrid(False)
    tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    # 列宽：名称列 Stretch，其余按内容自适应（上一版把它们也设成 Stretch，列间空隙更大）
    hh = tbl.horizontalHeader()
    hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    for c in (1, 2, 3):
        hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
    # 状态列的手动留白，避免 chip 紧贴名称列
    tbl.setColumnWidth(1, max(tbl.columnWidth(1), 120))
    for r, (nm, col, st, ver, dt) in enumerate(ROWS[name]):
        tbl.setItem(r, 0, QTableWidgetItem(nm))
        tbl.setCellWidget(r, 1, chip("● " + st, col))
        tbl.setItem(r, 2, QTableWidgetItem(ver))
        tbl.setItem(r, 3, QTableWidgetItem(dt))
        tbl.setRowHeight(r, 40)
    pl2.addWidget(tbl)
    idx = tabs.addTab(page, name)
    if name in TAB_COLOR:
        # ⚠️ setTabText 不解析 HTML（会原样显示 <span>），必须用 setTabTextColor
        tabs.tabBar().setTabTextColor(idx, QColor(TAB_COLOR[name]))
bl.addWidget(tabs)
outer.addWidget(body, 1)

# ---- 详情 + 底部 ----
detail = QFrame(); detail.setObjectName("card")
dl = QVBoxLayout(detail); dl.setContentsMargins(16, 12, 16, 12); dl.setSpacing(4)
d1 = QLabel("Carpet Extra   ·   🔴 阻塞"); d1.setStyleSheet("font-weight:600;")
d2 = QLabel("原因：最高只支持 MC 26.2，没有任何支持 26.3 的版本")
dl.addWidget(d1); dl.addWidget(d2)
outer.addWidget(detail)

foot = QHBoxLayout()
for b in ("导出 JSON", "导出 Markdown", "复制重跑命令"):
    foot.addWidget(QPushButton(b))
foot.addStretch(1)
st_lb = QLabel("配置目录：D:\\…\\config   ·   Modrinth 已启用"); st_lb.setObjectName("sub")
foot.addWidget(st_lb)
outer.addLayout(foot)

root.resize(1100, 780)
app.processEvents()          # 不 show()：grab 渲染不需要窗口可见
out = r"D:\Programme\python_prgram\mod-version-checker\docs\design\shot.png"
root.grab().save(out)
print("已渲染:", out)
