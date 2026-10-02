"""GUI 主题：颜色、字体、样式表与小组件。

所有颜色**与 CLI 的报告配色一致**（🔴🟠🟡⚪🟢⚫），这样同一个用户在两个界面之间
切换时不会产生"红黄颜色含义变了"的困惑。
颜色来源于 CLI 的 console.py（256 色 208 = 橙），这里换成对应的十六进制。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QStyle, QStyledItemDelegate, QWidget)

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

/* ---------- 输入控件 ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 10px;
    selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT};
}}
QLineEdit:hover, QSpinBox:hover {{ border-color: #C7CCD4; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 18px; border: none; background: transparent; }}
QCheckBox {{ spacing: 7px; }}

/* ---------- 列表 ---------- */
QListWidget {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px; }}
QListWidget::item {{ padding: 7px 8px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QListWidget::item:hover {{ background: #F5F7FA; }}

/* ---------- 下拉框的弹出列表 ----------
   QComboBox 的下拉是**独立的顶层视图**，不写这条它就用系统默认灰白样式，
   跟整体主题明显不搭（视觉评审发现）。 */
/* 弹出列表本身**不画边框** —— 边框交给外层容器（见 style_combo_popup），
   否则会出现「圆角框外面又套一个直角实线框」（视觉评审发现）。 */
QComboBox QAbstractItemView {{
    background: {CARD}; border: none; padding: 4px;
    outline: none; selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT};
}}
QComboBox QAbstractItemView::item {{ padding: 6px 8px; border: none; border-radius: 6px; }}
QComboBox QAbstractItemView::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
/* 给 QComboBox 设了边框之后 Qt 就**不再画原生箭头**，而 ::down-arrow 只认图片。
   用 border 假冒三角会被渲染成实心方块（踩过），所以这里用一张真正的小三角图。
   路径在运行时由 _arrow_qss() 注入（源码运行与打包后位置不同）。 */
QComboBox::drop-down {{ border: none; width: 26px; }}
__ARROW_QSS__

/* ---------- 滚动条 ----------
   默认滚动条是 Windows 原生样式（有箭头按钮、直角、灰蓝），与整体不搭。 */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #C9CFDA; border-radius: 5px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: #AEB6C4; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #C9CFDA; border-radius: 5px; min-width: 32px; }}
QScrollBar::handle:horizontal:hover {{ background: #AEB6C4; }}
/* 去掉两端的箭头按钮与空白页 */
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* ---------- 焦点提示 ----------
   默认的**虚线焦点框**（点列表/表格时文字周围那圈点线）与主题不符。
   注意：不能简单地 outline:none 了事 —— 那会让键盘用户完全看不到焦点在哪。
   这里改成"选中用底色、键盘焦点用一条主题色细边"，既好看又不丢可访问性。 */
QTableWidget::item:focus, QListWidget::item:focus, QTabBar::tab:focus {{ outline: none; }}
QTableWidget {{ outline: none; }}
QListWidget {{ outline: none; }}
QPushButton:focus {{ border: 1px solid {ACCENT}; }}
QPushButton#primary:focus {{ border: 1px solid {ACCENT_DARK}; }}
"""


class _PopupItemDelegate(QStyledItemDelegate):
    """下拉弹层的条目自绘。

    为什么需要它：Fusion 样式会给「当前项」画一个**直角焦点框**，
    而且那个框**样式表管不到** —— 试过 ::item 的 border / outline、
    控件级样式、去掉视图焦点、NoFrame + lineWidth(0)，方框依旧在
    （用户看到的就是"右侧和下侧两条线特别明显"）。

    与其继续和样式引擎较劲，不如自己画：**只画圆角底色和文字，不画任何边框**。
    """

    def paint(self, painter, option, index) -> None:
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QPalette

        painter.save()
        rect = QRectF(option.rect).adjusted(2, 2, -2, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(ACCENT_SOFT))
            painter.drawRoundedRect(rect, 6, 6)
        painter.setPen(QColor(TEXT if selected else TEXT))
        painter.drawText(option.rect.adjusted(10, 0, -8, 0),
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                         str(index.data() or ""))
        painter.restore()

    def sizeHint(self, option, index):                 # noqa: D102
        """行高必须按**字体真实高度**算。

        ⚠️ 两个极端都错过一次：
          · 硬编码 28 像素 -> 不同 DPI/字号下会**纵向重叠**，文字糊成一团；
          · 干脆不覆写 -> 自绘时行高不够，同样重叠（用户两次都看到了）。
        正确做法是取 option.fontMetrics.height() 再加上下留白。
        """
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), option.fontMetrics.height() + 12))
        return size


def style_combo_popup(combo) -> None:
    """给下拉框的弹层容器套上主题圆角边框。

    ⚠️ 必须用代码设置，QSS 够不着：弹层是一个**独立的顶层 QFrame**
    （combo.view().window()），QComboBox QAbstractItemView 只作用于里面的列表视图。
    不处理的话，列表视图的圆角边框外面会再套一层原生直角实线框 ——
    看起来就像「框外面莫名其妙多了一个方框」。
    """
    from PyQt6.QtWidgets import QFrame

    container = combo.view().window()
    if isinstance(container, QFrame):
        # frameShape=NoFrame 还不够：容器仍然保留 1px 的 frameWidth，
        # 画出来就是「圆角框里再套一个直角实线框」（实测 frameWidth 仍是 1）。
        # 做减法：**不给容器画边框**。
        # 之前我给它加了 1px 边框想"盖住"原生框，结果右/下两条线反而更明显
        # （用户原话是"越描越黑"）—— 原生框本来就在，再加一层只会叠加。
        # 现在只保留背景与圆角，视觉上干净且不会出现多余线条。
        container.setFrameShape(QFrame.Shape.NoFrame)
        container.setLineWidth(0)
        container.setMidLineWidth(0)
        container.setStyleSheet(
            f"QFrame {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px; }}")
    # 自绘条目：不再依赖样式表去"盖住"那个焦点框（盖不住，实测过四种写法）
    combo.view().setItemDelegate(_PopupItemDelegate(combo.view()))
    combo.view().setStyleSheet(
        f"QListView {{ background: transparent; border: none; outline: none; }}")


def _arrow_qss() -> str:
    """下拉箭头图的两条规则；找不到图就返回空串（**绝不能因此启动失败**）。"""
    import sys
    from pathlib import Path

    candidates = [Path(__file__).resolve().parents[3] / "assets"]
    if getattr(sys, "frozen", False):
        candidates.insert(0, Path(sys.argv[0]).resolve().parent / "assets")
    for base in candidates:
        normal, active = base / "arrow-down.png", base / "arrow-down-on.png"
        if normal.is_file():
            rule = (f"QComboBox::down-arrow {{ image: url({normal.as_posix()});"
                    " width: 10px; height: 6px; margin-right: 10px; }")
            if active.is_file():
                rule += (f"QComboBox::down-arrow:on {{ image: url({active.as_posix()}); }}")
            return rule
    return ""


QSS = QSS.replace("__ARROW_QSS__", _arrow_qss())


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
           "STATUS_COLOR", "STATUS_LABEL", "status_chip", "tab_widget", "style_combo_popup"]
