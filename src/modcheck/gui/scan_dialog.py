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

from modcheck.gui import theme


class ScanWorker(QThread):
    """扫描在后台跑：30 个 jar 要算哈希，界面不能卡。"""

    progressed = pyqtSignal(int, int, str)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, backend, folders, parent=None) -> None:
        super().__init__(parent)
        self._backend, self._folders = backend, folders
        self._stop = False

    def cancel(self) -> None:
        self._stop = True

    def run(self) -> None:                                   # noqa: D102
        try:
            report = self._backend.scan(
                self._folders,
                on_progress=lambda d, t, n: self.progressed.emit(d, t, n),
                should_stop=lambda: self._stop)
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
                      "会读取 jar 内信息并联网识别，结果合并进清单。")
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
        close.clicked.connect(self.accept)
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
            return
        folders = [self.list.item(i).text() for i in range(self.list.count())]
        if not folders:
            QMessageBox.information(self, "还没选文件夹", "请先添加至少一个 mods 文件夹。")
            return
        self._worker = ScanWorker(self._backend, folders, self)
        self._worker.progressed.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_finished)
        self.bar.setRange(0, 0)
        self.btn_scan.setText("取消")
        self.btn_save.setEnabled(False)
        self.lb_progress.setText("正在读取……")
        self._worker.start()

    def _on_progress(self, done: int, total: int, name: str) -> None:
        if self.bar.maximum() != total:
            self.bar.setRange(0, total)
        self.bar.setValue(done)
        # ⚠️ 读完最后一个 jar **不等于扫完**：后面还有「联网识别」阶段
        # （_resolve_slugs / _resolve_by_name），那里没有逐条进度回调，
        # 而且是**逐个出网搜索**的，几十个模组可能要好几分钟。
        # 之前界面就停在 "30/30" 一动不动，用户会以为程序卡死了 —— 这是真实反馈。
        if total and done >= total:
            self.bar.setRange(0, 0)          # 不确定进度：表明"在忙，但说不准还要多久"
            self.lb_progress.setText(
                "正在联网识别还没认出来的模组……（这一步要逐个搜索，可能要一会儿；"
                "可以点「取消」中止）")
            return
        self.lb_progress.setText(f"正在读取 {done}/{total}：{name}")

    def _on_done(self, report) -> None:
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
        # ⚠️ 被取消的扫描结果是"半份"的 —— scan_flow 明确要求**绝不许落盘**，
        # 否则用户会得到一份"看起来正常但实际上少了一半模组"的清单，
        # 而清单少了模组正是最危险的一类错误（升完级才发现某个模组不见了）。
        if getattr(report, "cancelled", False):
            self.lb_progress.setText(self.lb_progress.text() + "　⚠ 已取消，结果不完整，不能保存")
            self.btn_save.setEnabled(False)
            return
        self.btn_save.setEnabled(entries > 0)

    def _on_failed(self, message: str) -> None:
        self.lb_progress.setText("扫描失败")
        QMessageBox.warning(self, "扫描失败", message)

    def _on_finished(self) -> None:
        self._worker = None
        self.btn_scan.setText("开始扫描")
        self.bar.setRange(0, 1)
        self.bar.setValue(1 if self._report else 0)

    # ---------------------------------------------------------------- 保存
    def _on_save(self) -> None:
        name = self.ed_profile.text().strip()
        if not name:
            QMessageBox.information(self, "还没填清单名", "请填写要存入的清单名。")
            return
        try:
            outcome = self._backend.save_scan(self._report, name)
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", f"{type(exc).__name__}: {exc}")
            return
        added = getattr(outcome, "added", "?")
        merged = getattr(outcome, "merged", "?")
        total = getattr(outcome, "total", "?")
        QMessageBox.information(self, "已保存",
                                f"清单「{name}」已更新：\n"
                                f"新增 {added} 个，合并 {merged} 个，共 {total} 个模组")
        self.accept()


__all__ = ["ScanDialog"]
