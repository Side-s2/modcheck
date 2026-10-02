"""使用教程窗口（GUI 帮助菜单）。

内容来自 modcheck.gui.tutorial_content（与 docs/TUTORIAL.md 同源）。
这里只负责渲染，不写内容 —— 教程文案要改就改那个模块，CLI/文档/窗口三处不会漂移。
"""
from __future__ import annotations

from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget, QPushButton,
                             QScrollArea, QTextBrowser, QVBoxLayout, QWidget)

from modcheck.gui import theme


class TutorialDialog(QDialog):
    """左侧章节目录，右侧正文。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from modcheck.gui import tutorial_content as tc

        self._sections = tc.SECTIONS
        self.setWindowTitle(getattr(tc, "TITLE", "使用教程"))
        self.resize(1000, 700)
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        title = QLabel(self.windowTitle())
        title.setObjectName("title")
        outer.addWidget(title)
        hint = QLabel("建议按顺序读一遍；遇到具体问题可以直接跳到第 9 节「出问题了怎么办」。")
        hint.setObjectName("sub")
        outer.addWidget(hint)

        body = QHBoxLayout()
        body.setSpacing(12)
        self.list = QListWidget()
        self.list.setFixedWidth(240)
        for i, (heading, _) in enumerate(self._sections, start=1):
            self.list.addItem(f"{i}. {heading}")
        self.list.currentRowChanged.connect(self._show)
        body.addWidget(self.list)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setStyleSheet(
            f"QTextBrowser {{ background:{theme.CARD}; border:1px solid {theme.BORDER};"
            f"border-radius:8px; padding:14px; }}")
        body.addWidget(self.view, 1)
        outer.addLayout(body, 1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        close = QPushButton("关闭")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        foot.addWidget(close)
        outer.addLayout(foot)

        if self._sections:
            self.list.setCurrentRow(0)

    def _show(self, row: int) -> None:
        if row < 0 or row >= len(self._sections):
            return
        heading, paras = self._sections[row]
        html = [f"<h2 style='margin-top:0'>{_esc(heading)}</h2>"]
        for item in paras:
            kind, text = item[0], item[1]
            if kind == "h":
                html.append(f"<h3>{_esc(text)}</h3>")
            elif kind == "steps":
                lines = [ln for ln in str(text).split("\n") if ln.strip()]
                html.append("<ol>" + "".join(f"<li>{_esc(ln)}</li>" for ln in lines) + "</ol>")
            else:
                html.append(f"<p style='line-height:160%'>{_esc(text)}</p>")
        self.view.setHtml("".join(html))
        self.view.verticalScrollBar().setValue(0)


def _esc(text: object) -> str:
    """用户可见文本一律转义后再进 HTML —— 教程里出现 < 或 & 时不会破版。"""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\n", "<br>"))


__all__ = ["TutorialDialog"]
