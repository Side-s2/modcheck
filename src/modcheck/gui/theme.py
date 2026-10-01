"""GUI 主题：颜色、字体、样式表与小组件。

所有颜色**与 CLI 的报告配色一致**（🔴🟠🟡⚪🟢⚫），这样同一个用户在两个界面之间
切换时不会产生"红黄颜色含义变了"的困惑。
颜色来源于 CLI 的 console.py（256 色 208 = 橙），这里换成对应的十六进制。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

# ---------------------------------------------------------------- 颜色
BG = "#F4F5F7"          # 窗口底
CARD = "#FFFFFF"        # 卡片
BORDER = "#E4E7EC"
TEXT = "#1A1D21"
MUTED = "#6B7280"
ACCENT = "#2F6FED"
ACCENT_DARK = "#2A62D4"
ACCENT_SOFT = "#EAF0FE"

#: 与 CLI 的 Status 一一对应（CLI 侧：🟠 用 256 色 208）
STATUS_COLOR = {
    "blocked": "#E5484D",       # 🔴
    "prerelease": "#F76B15",    # 🟠
    "degraded": "#F5A524",      # 🟡
    "unknown": "#8B8D98",       # ⚪
    "ready": "#30A46C",         # 🟢
    "ignored": "#8B8D98",       # ⚫
}

#: 状态中文名（与 CLI 的 group.*.title 用词一致）
STATUS_LABEL = {
    "blocked": "阻塞",
    "prerelease": "仅存测试版",
    "degraded": "需注意",
    "unknown": "未判定",
    "ready": "就绪",
    "ignored": "已忽略",
}

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
QPushButton#primary:hover {{ background: {ACCENT_DARK}; }}
QPushButton#primary:disabled {{ background: #B9C6E8; }}
QPushButton {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px; padding: 9px 16px; }}
QPushButton:hover {{ border-color: #C7CCD4; }}
QPushButton:disabled {{ color: #B0B4BB; }}
QProgressBar {{ border: none; border-radius: 4px; background: #E9ECF1; height: 8px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QTabBar::tab {{ background: transparent; padding: 8px 12px; margin-right: 4px; border-radius: 8px; }}
QTabBar::tab:selected {{ background: {ACCENT_SOFT}; }}
QTableWidget {{ border: none; gridline-color: transparent; background: {CARD};
                selection-background-color: {ACCENT_SOFT}; }}
QTableWidget::item {{ padding: 10px 8px; border-bottom: 1px solid #F0F2F5; }}
QTableWidget::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QHeaderView::section {{ background: {CARD}; border: none; border-bottom: 1px solid {BORDER};
                        padding: 10px 8px; color: {MUTED}; font-weight: 600; text-align: left; }}
"""


def status_chip(status: str) -> QLabel:
    """状态色标签（圆点 + 文字），颜色与 CLI 一致。"""
    color = STATUS_COLOR.get(status, MUTED)
    label = QLabel("● " + STATUS_LABEL.get(status, status))
    label.setStyleSheet(f"color:{color}; font-weight:600; background:transparent;")
    return label


def tab_widget(text: str, status: str | None = None) -> QWidget:
    """页签内容：状态色圆点 + 文字。

    ⚠️ 两个坑（都实测踩过）：
      1. 不能用 setTabText 传 HTML —— 它不解析，会把 <span> 原样显示；
      2. 不能用 setTabTextColor 给整条上色 —— **选中态会被 QSS 覆盖，状态色就丢了**。
    所以圆点必须是独立控件，这样任何选中态都盖不掉它。
    """
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(4, 2, 4, 2)
    lay.setSpacing(6)
    if status:
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{STATUS_COLOR.get(status, MUTED)}; font-size:15px;"
                          "background:transparent;")
        lay.addWidget(dot)
    label = QLabel(text)
    label.setStyleSheet("background:transparent;")
    lay.addWidget(label)
    return box


__all__ = ["BG", "CARD", "BORDER", "TEXT", "MUTED", "ACCENT", "ACCENT_SOFT", "QSS",
           "STATUS_COLOR", "STATUS_LABEL", "status_chip", "tab_widget"]
