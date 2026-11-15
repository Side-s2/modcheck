"""在应用内显示随程序分发的使用教程。"""
from __future__ import annotations

from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QFont, QPalette, QTextBlockFormat, QTextLength, QTextTable
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QListWidget, QPushButton, QTextBrowser,
                             QVBoxLayout, QWidget)

from modcheck.gui.tutorial_content import MARKDOWN, TITLE


class TutorialDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.resize(930, 700)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        body = QHBoxLayout()
        body.setSpacing(16)
        self.chapters = QListWidget()
        self.chapters.setObjectName("tutorialChapters")
        self.chapters.setFixedWidth(228)
        self._sections = MARKDOWN.removeprefix("## ").split("\n## ")
        self.chapters.addItems(section.splitlines()[0] for section in self._sections)
        self.view = QTextBrowser()
        self.view.setObjectName("tutorialText")
        self.view.setOpenExternalLinks(True)
        font = QFont(self.font())
        font.setFamilies(["DengXian", "Noto Sans CJK SC", *font.families()])
        font.setPixelSize(14)
        self.chapters.setFont(font)
        font.setPixelSize(16)
        self.view.document().setDefaultFont(font)
        self.chapters.currentRowChanged.connect(self._show_chapter)
        body.addWidget(self.chapters)
        body.addWidget(self.view, 1)
        layout.addLayout(body, 1)
        self.chapters.setCurrentRow(0)

        footer = QHBoxLayout()
        footer.addStretch()
        close = QPushButton("关闭")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        layout.addLayout(footer)

    def _show_chapter(self, row: int) -> None:
        if row < 0:
            return
        document = self.view.document()
        link = self.palette().color(QPalette.ColorRole.Link).name()
        document.setDefaultStyleSheet(f"a {{ color: {link}; }}")
        document.setMarkdown("## " + self._sections[row])
        document.setDocumentMargin(8)
        block = document.begin()
        while block.isValid():
            cursor = self.view.textCursor()
            cursor.setPosition(block.position())
            style = cursor.blockFormat()
            style.setLineHeight(155, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
            if style.headingLevel():
                style.setTopMargin(16 if block.position() else 0)
                style.setBottomMargin(12)
            elif cursor.currentList() is not None:
                style.setBottomMargin(5)
            else:
                style.setBottomMargin(10)
            cursor.setBlockFormat(style)
            block = block.next()
        for frame in document.rootFrame().childFrames():
            if isinstance(frame, QTextTable):
                table = frame.format()
                table.setWidth(QTextLength(QTextLength.Type.PercentageLength, 100))
                table.setCellPadding(5)
                table.setBorderBrush(self.palette().mid())
                frame.setFormat(table)
        self.view.verticalScrollBar().setValue(0)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "view"):
            scroll = self.view.verticalScrollBar()
            position = scroll.value()
            self._show_chapter(self.chapters.currentRow())
            scroll.setValue(position)


__all__ = ["TutorialDialog"]
