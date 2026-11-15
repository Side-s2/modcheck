"""应用调色板及 GUI 控件样式。"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainterPath, QPalette, QPolygon, QRegion
from PyQt6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QListView, QMenu,
                             QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget)

STATUS_LABEL = {
    "blocked": "阻塞",
    "prerelease": "仅存测试版",
    "degraded": "需注意",
    "unknown": "未判定",
    "ready": "就绪",
    "ignored": "已忽略",
}

# 还原初版圆点色。小字号的状态文字沿用同色系较深的色值。
_LIGHT_STATUS_DOTS = {
    "blocked": "#E5484D", "prerelease": "#F76B15", "degraded": "#F5A524",
    "unknown": "#8B8D98", "ready": "#30A46C", "ignored": "#8B8D98",
}
_LIGHT_STATUS = {
    "blocked": "#BE3137", "prerelease": "#AD470A", "degraded": "#8B5D15",
    "unknown": "#595D69", "ready": "#18754B", "ignored": "#626572",
}
_DARK_STATUS = {
    "blocked": "#FFADB1", "prerelease": "#FFAE7D", "degraded": "#F5C66A",
    "unknown": "#BEC6D4", "ready": "#7DDBAB", "ignored": "#BEC6D4",
}


def _arrow_qss() -> str:
    normal = Path(__file__).resolve().with_name("arrow-down.png")
    active = normal.with_name("arrow-down-on.png")
    return (f'QComboBox::down-arrow {{ image: url("{normal.as_posix()}");'
            ' width: 10px; height: 6px; margin-right: 7px; }'
            f'QComboBox::down-arrow:on {{ image: url("{active.as_posix()}"); }}')


QSS = """
QWidget#root, QDialog, QMenuBar { background: palette(window); color: palette(window-text); }
QFrame#card { background: palette(base); border: 1px solid palette(mid); border-radius: 10px; }
QLabel#title { font-size: 17px; font-weight: 600; }
QLabel#sub { color: palette(placeholder-text); font-size: 12px; }
QLabel#cacheNotice { color: palette(placeholder-text); }
QComboBox {
    combobox-popup: 0; background: palette(base); border: 1px solid palette(mid);
    border-radius: 8px; padding: 7px 26px 7px 12px; min-width: 135px;
}
QComboBox::drop-down { border: none; width: 24px; }
QComboBox:disabled { color: palette(placeholder-text); }
QListView#comboItems {
    background: palette(base); padding: 5px; border: 1px solid palette(mid); border-radius: 8px;
    selection-background-color: palette(highlight); selection-color: palette(highlighted-text);
}
QListView#comboItems::item { padding: 6px 8px; border: 0; border-radius: 5px; }
QListView#comboItems::item:selected { background: palette(highlight); color: palette(highlighted-text); }

QPushButton { background: palette(button); border: 1px solid palette(mid);
              border-radius: 8px; padding: 9px 16px; }
QPushButton#primary { background: #2F6FED; color: white; border: 1px solid #2F6FED;
                      padding: 9px 22px; font-weight: 600; }
QPushButton#primary:hover { background: #245DCD; }
QPushButton:disabled, QPushButton#primary:disabled {
    color: palette(placeholder-text); background: palette(alternate-base); border-color: palette(mid);
}
QProgressBar { border: 0; border-radius: 4px; background: palette(alternate-base); height: 8px; }
QProgressBar::chunk { background: #2F6FED; border-radius: 4px; }
QTabBar::tab { background: transparent; padding: 8px 12px; margin-right: 4px; border-radius: 8px; }
QTabBar::tab:selected { background: palette(highlight); }
QTableWidget { border: 0; gridline-color: transparent; background: palette(base); }
QTableWidget::item { padding: 10px 8px; border-bottom: 1px solid palette(alternate-base); }
QHeaderView::section { background: palette(base); border: 0; border-bottom: 1px solid palette(mid);
                       padding: 10px 8px; color: palette(placeholder-text); font-weight: 600; }
QLineEdit, QSpinBox, QDoubleSpinBox, QListWidget, QTextBrowser {
    background: palette(base); border: 1px solid palette(mid); border-radius: 8px;
}
QLineEdit, QSpinBox, QDoubleSpinBox { padding: 7px 10px; }
QCheckBox { spacing: 7px; }
QListWidget { padding: 4px; }
QListWidget::item { padding: 7px 8px; border-radius: 6px; }
QListWidget::item:hover:!selected { background: palette(alternate-base); }
QTextBrowser { padding: 14px; }
QTextBrowser#tutorialText QScrollBar:vertical {
    width: 9px; margin: 2px; background: transparent;
}
QTextBrowser#tutorialText QScrollBar::handle:vertical {
    background: palette(mid); min-height: 24px; border-radius: 3px;
}
QTextBrowser#tutorialText QScrollBar::add-line:vertical,
QTextBrowser#tutorialText QScrollBar::sub-line:vertical { height: 0; }
QTextBrowser#tutorialText QScrollBar::add-page:vertical,
QTextBrowser#tutorialText QScrollBar::sub-page:vertical { background: transparent; }
QListWidget#tutorialChapters { border: 0; padding: 4px; }
QListWidget#tutorialChapters::item, QListWidget#profileList::item {
    min-height: 36px; padding: 2px 12px; margin: 2px 0; border: 0; border-radius: 6px;
}
QListWidget#tutorialChapters::item:selected, QListWidget#profileList::item:selected {
    background: palette(highlight); color: palette(highlighted-text);
}
QMenu {
    background: palette(base); color: palette(text); border: 1px solid palette(mid);
    border-radius: 9px; padding: 5px;
}
QMenu::item { padding: 7px 22px 7px 12px; border-radius: 5px; }
QMenuBar::item { padding: 4px 8px; border-radius: 5px; }
QMenu::item:selected, QMenuBar::item:selected {
    background: palette(highlight); color: palette(highlighted-text);
}
QToolTip { background: palette(tool-tip-base); color: palette(tool-tip-text); border: 1px solid palette(mid); }
QPushButton:hover, QComboBox:hover, QLineEdit:hover,
QSpinBox:hover, QDoubleSpinBox:hover { border-color: #2F6FED; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QPushButton:focus, QPushButton#primary:focus, QListWidget:focus {
    border: 1px solid #2F6FED;
}
QPushButton#primary:focus { border-color: white; }
""" + _arrow_qss()


def apply_theme(app: QApplication, preference: str = "auto") -> None:
    """Apply the saved appearance preference."""
    app.setProperty("modcheckTheme", preference)
    dark = (preference == "dark"
            or (preference == "auto" and app.styleHints().colorScheme() == Qt.ColorScheme.Dark))
    role = QPalette.ColorRole
    colors = {
        role.Window: "#191D25" if dark else "#F6FAFF",
        role.Base: "#212632" if dark else "#FFFFFF",
        role.AlternateBase: "#2C3443" if dark else "#EAF3FF",
        role.Button: "#252C39" if dark else "#FFFFFF",
        role.Mid: "#4B5568" if dark else "#C5D6F0",
        role.WindowText: "#E9EDF4" if dark else "#14213A",
        role.PlaceholderText: "#A8B3C5" if dark else "#4A5F7C",
        role.Highlight: "#384E77" if dark else "#D7E8FF",
        role.HighlightedText: "#FFFFFF" if dark else "#173E85",
        role.Link: "#94BAFF" if dark else "#1D54BC",
    }
    palette = QPalette()
    for key, value in colors.items():
        palette.setColor(key, QColor(value))
    for key in (role.Text, role.ButtonText, role.ToolTipText):
        palette.setColor(key, palette.color(role.WindowText))
        palette.setColor(QPalette.ColorGroup.Disabled, key, palette.color(role.PlaceholderText))
    palette.setColor(role.ToolTipBase, palette.color(role.Base))
    app.setPalette(palette)
    status_colors = _DARK_STATUS if dark else _LIGHT_STATUS
    dot_colors = _DARK_STATUS if dark else _LIGHT_STATUS_DOTS
    status_rules = []
    for status, color in status_colors.items():
        status_rules.append(f'QLabel[status="{status}"] {{ color: {color}; background: transparent; }}')
        status_rules.append(f'QLabel[statusDot="{status}"] {{ color: {dot_colors[status]};'
                            ' background: transparent; }')
    if not dark:
        status_rules.append("QLabel[statusDot] { font-size: 15px; }")
    app.setStyleSheet(QSS + "\n".join(status_rules))


def setup_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    font = app.font()
    font.setFamilies(["Microsoft YaHei UI", "Segoe UI", *font.families()])
    font.setPixelSize(13)
    app.setFont(font)
    apply_theme(app)

    def system_changed(_scheme) -> None:
        if app.property("modcheckTheme") == "auto":
            apply_theme(app)

    app.styleHints().colorSchemeChanged.connect(system_changed)


class RoundedMenu(QMenu):
    """Clip the native popup surface to the menu's rounded edge."""

    def _update_mask(self) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 9, 9)
        self.setMask(QRegion(QPolygon(path.toFillPolygon().toPolygon())))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._update_mask()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_mask()


class _ComboItemDelegate(QStyledItemDelegate):
    """Use the selected row highlight as the keyboard focus indicator."""

    def paint(self, painter, option, index) -> None:
        styled = QStyleOptionViewItem(option)
        if styled.state & QStyle.StateFlag.State_HasFocus:
            styled.state |= QStyle.StateFlag.State_Selected
        styled.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, styled, index)


def style_combo_popup(combo: QComboBox) -> None:
    view = QListView(combo)
    view.setObjectName("comboItems")
    view.setUniformItemSizes(True)
    combo.setView(view)
    combo.setItemDelegate(_ComboItemDelegate(view))
    view.setFrameShape(QFrame.Shape.NoFrame)


def set_status(label: QLabel, status: str) -> None:
    label.setProperty("status", status)
    style = label.style()
    style.unpolish(label)
    style.polish(label)
    label.update()


def _status_dot(status: str) -> QLabel:
    dot = QLabel("●")
    dot.setProperty("statusDot", status)
    return dot


def status_chip(status: str, text: str | None = None) -> QWidget:
    label = QLabel(text if text is not None else STATUS_LABEL.get(status, status))
    label.setProperty("status", status)
    chip = QWidget()
    chip.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    layout = QHBoxLayout(chip)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(5)
    layout.addWidget(_status_dot(status))
    layout.addWidget(label, 1)
    return chip


def tab_widget(text: str, status: str | None = None) -> QWidget:
    box = QWidget()
    box.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    layout = QHBoxLayout(box)
    layout.setContentsMargins(4, 2, 4, 2)
    layout.setSpacing(6)
    if status:
        layout.addWidget(_status_dot(status))
    layout.addWidget(QLabel(text))
    return box
