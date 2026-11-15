"""扫描对话框（GUI 三期）：选文件夹 → 扫描识别 → 存成清单。

识别与落盘全部来自 flows/scan_flow.py（与 CLI 的 scan 同一套），
界面只负责选目录、显示进度、报结果。
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QLabel,
                             QLineEdit, QListWidget, QMessageBox, QProgressBar, QPushButton,
                             QVBoxLayout, QWidget)

from modcheck.gui.dialogs import describe, show_info, show_warning


class ScanWorker(QThread):
    """扫描在后台跑：30 个 jar 要算哈希，界面不能卡。"""

    progressed = pyqtSignal(int, int, str)
    network_progressed = pyqtSignal(int, int, str)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, backend, folders, parent=None) -> None:
        super().__init__(parent)
        self._backend, self._folders = backend, folders

    def cancel(self) -> None:
        self.requestInterruption()

    def run(self) -> None:                                   # noqa: D102
        try:
            report = self._backend.scan(
                self._folders,
                on_progress=lambda d, t, n: self.progressed.emit(d, t, n),
                should_stop=self.isInterruptionRequested,
                on_network_progress=lambda d, t, n: self.network_progressed.emit(d, t, n))
            self.done.emit(report)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class ScanDialog(QDialog):
    """扫描 mods 文件夹并建立清单。"""

    def __init__(self, backend, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._backend = backend
        self._worker: ScanWorker | None = None
        self._report = None
        self._close_when_finished = False
        self.setWindowTitle("扫描 mods 文件夹")
        self.resize(760, 560)
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(12)

        title = QLabel("扫描 mods 文件夹")
        title.setObjectName("title")
        outer.addWidget(title)
        hint = QLabel("选一个或多个文件夹（例如服务端根目录下的 mods）。"
                      "会读取 jar 内信息并联网识别。重复扫描会更新匹配条目的安装信息。")
        hint.setObjectName("sub")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        row = QHBoxLayout()
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        row.addWidget(self.list, 1)
        col = QVBoxLayout()
        for text, slot in (("添加文件夹…", self._on_add), ("移除所选", self._on_remove)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            col.addWidget(b)
        col.addStretch(1)
        row.addLayout(col)
        outer.addLayout(row, 1)

        prow = QHBoxLayout()
        prow.addWidget(QLabel("存入清单"))
        self.ed_profile = QLineEdit("服务器A")
        prow.addWidget(self.ed_profile, 1)
        outer.addLayout(prow)

        self.lb_progress = QLabel("尚未开始")
        self.lb_progress.setObjectName("sub")
        self.lb_progress.setWordWrap(True)
        outer.addWidget(self.lb_progress)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        outer.addWidget(self.bar)

        foot = QHBoxLayout()
        self.btn_scan = QPushButton("开始扫描")
        self.btn_scan.setObjectName("primary")
        self.btn_scan.clicked.connect(self._on_scan)
        foot.addWidget(self.btn_scan)
        self.btn_save = QPushButton("保存到清单")
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self._on_save)
        foot.addWidget(self.btn_save)
        foot.addStretch(1)
        close = QPushButton("关闭")
        close.clicked.connect(self.reject)
        foot.addWidget(close)
        outer.addLayout(foot)

    # ---------------------------------------------------------------- 选目录
    def _on_add(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "选择 mods 文件夹")
        if chosen:
            existing = {self.list.item(i).text() for i in range(self.list.count())}
            if chosen not in existing:
                self.list.addItem(chosen)

    def _on_remove(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))

    # ---------------------------------------------------------------- 扫描
    def _on_scan(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.lb_progress.setText("正在取消……")
            self.btn_scan.setEnabled(False)
            return
        folders = [self.list.item(i).text() for i in range(self.list.count())]
        if not folders:
            QMessageBox.information(self, "还没选文件夹", "请先添加至少一个 mods 文件夹。")
            return
        self._report = None
        self.lb_progress.setToolTip("")
        self._worker = ScanWorker(self._backend, folders, self)
        self._worker.progressed.connect(self._on_progress)
        self._worker.network_progressed.connect(self._on_network_progress)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._worker.deleteLater)
        self.bar.setRange(0, 0)
        self.btn_scan.setText("取消")
        self.btn_save.setEnabled(False)
        self.lb_progress.setText("正在读取……")
        self._worker.start()

    def _on_progress(self, done: int, total: int, name: str) -> None:
        if self.btn_scan.isEnabled():
            self.bar.setRange(0, total)
            self.bar.setValue(done - 1)
            self.lb_progress.setText(f"正在读取 {done}/{total}：{name}")

    def _on_network_progress(self, done: int, total: int, operation: str) -> None:
        if self.btn_scan.isEnabled():
            self.bar.setRange(0, total)
            self.bar.setValue(done - 1)
            self.lb_progress.setText(f"联网识别 {done}/{total}：{operation}")

    def _on_done(self, report) -> None:
        if not self.btn_scan.isEnabled() or report.cancelled:
            self.lb_progress.setText("扫描已取消。")
            return
        self._report = report
        entries = len(getattr(report, "entries", []) or [])
        skipped = len(getattr(report, "skipped", []) or [])
        subdirs = len(getattr(report, "subdirs", []) or [])
        by_hash = getattr(report, "by_hash", 0)
        by_meta = getattr(report, "by_meta", 0)
        by_search = getattr(report, "by_search", 0)
        self.lb_progress.setText(
            f"扫描完成：识别出 {entries} 个模组"
            f"（指纹 {by_hash} / jar 信息 {by_meta} / 名称搜索 {by_search}）"
            f"，跳过 {skipped} 个文件"
            + (f"，{subdirs} 个子目录未展开" if subdirs else ""))
        if report.warnings:
            detail = "\n".join(report.warnings)
            self.lb_progress.setText(self.lb_progress.text() + "\n" + report.warnings[0].strip())
            self.lb_progress.setToolTip(detail)

    def _on_failed(self, message: str) -> None:
        if self._close_when_finished:
            return
        self.lb_progress.setText("扫描失败")
        show_warning(self, "扫描失败",
                     "扫描没能完成，**没有**写入任何清单。\n"
                     "请确认所选文件夹存在且可读，然后重试。",
                     detail=message)

    def _on_finished(self) -> None:
        self._worker = None
        if self._close_when_finished:
            super().reject()
            return
        self.btn_scan.setText("开始扫描")
        self.btn_scan.setEnabled(True)
        self.btn_save.setEnabled(bool(self._report and self._report.entries))
        self.bar.setRange(0, 1)
        self.bar.setValue(1 if self._report else 0)

    def done(self, status: int) -> None:
        if self._worker is not None:
            self._close_when_finished = True
            self._on_scan()
            return
        super().done(status)

    # ---------------------------------------------------------------- 保存
    def _on_save(self) -> None:
        name = self.ed_profile.text().strip()
        if not name:
            QMessageBox.information(self, "还没填清单名", "请填写要存入的清单名。")
            return
        try:
            outcome = self._backend.save_scan(self._report, name)
        except Exception as exc:
            show_warning(self, "保存失败",
                         "清单没能保存，扫描结果**没有**写入。\n"
                         "常见原因：磁盘空间不足，或清单文件被其它程序占用。",
                         detail=describe(exc))
            return
        # ⚠️ outcome.merged 是 **list[ModEntry]**，不是数字！
        # 之前写 f"合并 {merged} 个" 会把整个对象列表的 repr 打出来 ——
        # 用户看到的是一屏 ModEntry(key=..., display_name=...)，这就是"巨长且全是编程语言"的来源。
        total = len(getattr(outcome, "merged", []) or [])
        stats = getattr(outcome, "stats", None)
        added = getattr(stats, "added", None)
        merged_n = getattr(stats, "merged", None)
        bits = []
        if added is not None:
            bits.append(f"新增 {added} 个")
        if merged_n is not None:
            bits.append(f"合并 {merged_n} 个")
        bits.append(f"清单现有 {total} 个模组")
        created = getattr(outcome, "created", False)
        head = f"已新建清单「{name}」。" if created else f"清单「{name}」已更新。"
        show_info(self, "已保存", head + "\n" + "，".join(bits) + "\n\n可以回主窗口点「开始检查」了。")
        self.accept()


__all__ = ["ScanDialog"]
