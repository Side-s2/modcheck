"""统一的对话框助手。

一条规矩：**主文案说人话，技术细节折叠进「详细信息」。**

为什么要有这个模块：之前十几处直接写 f"{type(exc).__name__}: {exc}"，
甚至 f"合并 {某个对象列表} 个" —— 用户看到的是
「TypeError: expected str...」或一屏 ModEntry(key=..., display_name=...)，
既读不懂、也不知道该做什么。**把编程语言暴露给用户等于没给提示。**
"""
from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox, QWidget


def describe(exc: BaseException) -> str:
    """异常 → 技术细节文本（只进「详细信息」，不作为主文案）。"""
    return f"{type(exc).__name__}: {exc}"


def show_info(parent: QWidget | None, title: str, message: str, *, detail: str = "") -> None:
    """提示（成功/说明类）。主文案一句话，细节可选。"""
    _show(parent, QMessageBox.Icon.Information, title, message, detail)


def show_warning(parent: QWidget | None, title: str, message: str, *, detail: str = "") -> None:
    """警告（失败类）。**必须说清"发生了什么"和"你可以怎么做"**，不要只报异常。"""
    _show(parent, QMessageBox.Icon.Warning, title, message, detail)


def show_error(parent: QWidget | None, title: str, message: str, *, detail: str = "") -> None:
    """错误（启动失败等）。"""
    _show(parent, QMessageBox.Icon.Critical, title, message, detail)


def _show(parent, icon, title: str, message: str, detail: str) -> None:
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(message)
    if detail:
        # Qt 会自动加一个「Show Details...」折叠按钮 —— 想看的人看得到，
        # 不想看的人不会被一屏英文淹没。
        box.setDetailedText(detail)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


__all__ = ["describe", "show_error", "show_info", "show_warning"]
