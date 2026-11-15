"""下载对话框（GUI 三期第二半）：把「建议的模组版本」下到指定文件夹。

流程刻意分成两步 —— **先给用户看清楚要下什么，再动手**：
    选目录 → prepare（只选品与查冲突，不写盘不建目录）→ 展示计划与冲突 → 确认 → 下载 → 汇总

判定与下载全部来自 core/downloader.py 与 flows/download_flow.py（与 CLI 同一套），
界面只负责展示与询问。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Event

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QFileDialog, QHBoxLayout,  # noqa: F401
                             QHeaderView, QLabel, QListWidget, QMessageBox, QProgressBar, QPushButton,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from modcheck.errors import ConfigError
from modcheck.core.downloader import SKIP_TARGET_APPEARED, STATUS_CANCELLED
from modcheck.gui.dialogs import describe, show_warning
from modcheck.i18n import t


def _size_mb(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB" if n else "—"


class CandidateConflictDialog(QDialog):
    def __init__(self, parent: QWidget, target: Path, message: str, items, *,
                 existing: bool, directory: bool) -> None:
        super().__init__(parent)
        self.choice: int | None = None
        self.setWindowTitle("同名文件")
        self.resize(620, 380)
        layout = QVBoxLayout(self)
        title = QLabel(f"{target.name}\n{message}")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        title.setToolTip(str(target))
        layout.addWidget(title)
        candidates = QListWidget()
        for item in items:
            candidates.addItem(_candidate_text(item))
            candidate = candidates.item(candidates.count() - 1)
            candidate.setToolTip(item.file.url + "\nSHA-1 " + (item.file.hashes.get("sha1") or "未知"))
        layout.addWidget(candidates, 1)
        buttons = QHBoxLayout()
        skip = QPushButton("跳过")
        skip.clicked.connect(self.accept)
        skip.setDefault(True)
        buttons.addWidget(skip)
        choose = QPushButton("用所选构建覆盖" if existing else "下载所选构建")
        choose.setEnabled(False)
        if not directory:
            def use_candidate() -> None:
                if candidates.currentRow() >= 0:
                    self.choice = candidates.currentRow()
                    self.accept()

            candidates.currentRowChanged.connect(lambda row: choose.setEnabled(row >= 0))
            choose.clicked.connect(use_candidate)
            buttons.addWidget(choose)
        buttons.addStretch()
        cancel = QPushButton("取消本次下载")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)


def _candidate_text(item) -> str:
    slug = item.entry.sources.get("modrinth") or item.entry.key
    size = f"{item.file.size:,} 字节" if item.file.size else "大小未知"
    return f"{item.entry.best_name}（{slug}） · {item.version.version_number} · {size}"


class DownloadWorker(QThread):
    """下载在后台跑；进度按"第几个文件"回报（单文件内部字节数由 core 统计）。"""

    progressed = pyqtSignal(int, int, str)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, backend, prep, selected, overwrite, parent=None) -> None:
        super().__init__(parent)
        self._backend, self._prep, self._selected = backend, prep, selected
        self._overwrite = overwrite
        self._stop = Event()

    def cancel(self) -> None:
        self._stop.set()

    def run(self) -> None:                                   # noqa: D102
        total = len(self._prep.plan.items)
        done = 0

        def on_item(item, _ok: bool) -> None:
            nonlocal done
            if item.status != STATUS_CANCELLED:
                done += 1
                self.progressed.emit(done, total, item.target.name)

        try:
            outcome = self._backend.run_download(
                self._prep, selected=self._selected, overwrite=self._overwrite,
                on_item=on_item,
                should_stop=self._stop.is_set)
            self.done.emit(outcome)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class DownloadDialog(QDialog):
    """下载建议的模组版本。"""

    def __init__(self, backend, report, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._backend = backend
        self._report = report            # 来自一次检查的 Report
        self._prep = None
        self._dir: Path | None = None
        self._worker: DownloadWorker | None = None
        self._close_pending = False
        self.setWindowTitle("下载建议的模组版本")
        self.resize(940, 620)
        self._build()

    # ---------------------------------------------------------------- 构建
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(10)

        title = QLabel("下载建议的模组版本")
        title.setObjectName("title")
        outer.addWidget(title)
        # ⚠️ QLabel 默认按纯文本渲染，写 **加粗** 会原样显示星号（实测）。
        # 要加粗就得用富文本，或者干脆不加 —— 这里选择不加，避免多一处 HTML 注入面。
        self.lb_hint = QLabel(
            "默认下载「就绪」和「需注意」的建议版本。可勾选包含测试版。")
        self.lb_hint.setObjectName("sub")
        self.lb_hint.setWordWrap(True)
        outer.addWidget(self.lb_hint)

        row = QHBoxLayout()
        row.addWidget(QLabel("下载到"))
        self.ed_dir = QLabel("（未选择）")
        self.ed_dir.setObjectName("sub")
        row.addWidget(self.ed_dir, 1)
        self.btn_pick = QPushButton("选择文件夹…")
        self.btn_pick.clicked.connect(self._on_pick)
        row.addWidget(self.btn_pick)
        outer.addLayout(row)

        self.ck_prerelease = QCheckBox("同时下载测试性模组（🟠 仅存测试版）")
        self.ck_prerelease.setToolTip(
            "🟠 的模组只有测试版（beta / alpha）支持目标版本，稳定性没有保证。\n"
            "默认不下载；勾选后会一并下载，但请自行评估风险并先备份存档。")
        self.ck_prerelease.setEnabled(False)          # 选了文件夹才算得出有没有可下的
        self.ck_prerelease.toggled.connect(self._on_toggle_prerelease)
        outer.addWidget(self.ck_prerelease)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["模组", "版本", "文件名", "大小", "目标"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(4, 120)
        self.table.verticalHeader().setDefaultSectionSize(34)
        outer.addWidget(self.table, 1)

        self.lb_skip = QLabel("")
        self.lb_skip.setObjectName("sub")
        self.lb_skip.setWordWrap(True)
        outer.addWidget(self.lb_skip)

        self.lb_progress = QLabel("先选择目标文件夹")
        self.lb_progress.setObjectName("sub")
        self.lb_progress.setWordWrap(True)
        outer.addWidget(self.lb_progress)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        outer.addWidget(self.bar)

        foot = QHBoxLayout()
        self.btn_go = QPushButton("开始下载")
        self.btn_go.setObjectName("primary")
        self.btn_go.setEnabled(False)
        self.btn_go.clicked.connect(self._on_go)
        foot.addWidget(self.btn_go)
        foot.addStretch(1)
        close = QPushButton("关闭")
        close.clicked.connect(self.reject)
        foot.addWidget(close)
        outer.addLayout(foot)

    # ---------------------------------------------------------------- 准备
    def _on_pick(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "选择下载目标文件夹")
        if not chosen:
            return
        target = Path(chosen)
        # 目标像是"正在用的 mods 文件夹"时先提醒一次（PRD §14.5 第 14 条：允许，但要说清）
        if self._backend.looks_like_mods_dir(target):
            if QMessageBox.question(
                    self, "这看起来是你的 mods 文件夹",
                    f"{target}\n\n这看起来是**正在使用**的 mods 文件夹。\n"
                    "往这里写文件会直接改变服务器加载的模组。\n\n仍然选择它吗？"
                    ) != QMessageBox.StandardButton.Yes:
                return
        self.ed_dir.setText(str(target))
        self._dir = target
        self.ck_prerelease.setEnabled(True)
        self._reprepare()

    def _on_toggle_prerelease(self, _checked: bool) -> None:
        """切换「同时下载测试性模组」—— 计划要按新口径**重算**，不能只改显示。"""
        self._reprepare()

    def _reprepare(self) -> None:
        if self._dir is None:
            return
        try:
            self._prep = self._backend.prepare_download(
                self._report, self._dir,
                include_prerelease=self.ck_prerelease.isChecked())
        except ConfigError as exc:
            self._prep = None
            self.table.setRowCount(0)
            self.lb_skip.clear()
            self.lb_progress.setText(exc.message)
            self.btn_go.setEnabled(False)
            return
        except Exception as exc:
            self._prep = None
            self.table.setRowCount(0)
            self.lb_skip.clear()
            self.btn_go.setEnabled(False)
            show_warning(self, "准备失败",
                         "没能生成下载清单。请确认所选文件夹存在且可写。",
                         detail=describe(exc))
            return
        self._fill()

    def _fill(self) -> None:
        prep = self._prep
        items = list(prep.plan.items)
        groups = prep.same_name_groups()
        conflicts = {index for group in groups for index in group}
        self.table.setRowCount(0)
        self.table.setRowCount(len(items))
        for i, item in enumerate(items):
            entry = item.entry
            name = getattr(entry, "display_name", "") or entry.file_name or entry.key
            self.table.setItem(i, 0, QTableWidgetItem(str(name)))
            self.table.setItem(i, 1, QTableWidgetItem(item.version.version_number))
            self.table.setItem(i, 2, QTableWidgetItem(item.target.name))
            self.table.setItem(i, 3, QTableWidgetItem(_size_mb(getattr(item.file, "size", 0))))
            self.table.setItem(i, 4, QTableWidgetItem("同名待确认" if i in conflicts else "—"))
        n_conflict = len(groups)
        skipped_bits = []
        if prep.no_jar:
            skipped_bits.append(f"{len(prep.no_jar)} 个模组没有可下载的 jar")
        if prep.no_version:
            skipped_bits.append(f"{len(prep.no_version)} 个模组在目标版本上没有可用版本")
        if prep.extra_files:
            skipped_bits.append(f"{prep.extra_files} 个模组另有附属文件（不下）")
        self.lb_skip.setText("；".join(skipped_bits) or "")
        self.lb_progress.setText(
            f"待处理 {len(items)} 个文件" + (f"，{n_conflict} 组同名文件将在下载前确认" if n_conflict else ""))
        self.btn_go.setEnabled(bool(items))

    # ---------------------------------------------------------------- 下载
    def _confirm_conflicts(self) -> tuple[dict[int, bool], dict[str, bool]] | None:
        selected: dict[int, bool] = {}
        overwrite: dict[str, bool] = {}
        for indexes in self._prep.same_name_groups():
            items = [self._prep.plan.items[index] for index in indexes]
            target = items[0].target
            try:
                info = target.lstat()
            except FileNotFoundError:
                info = None
            except OSError as exc:
                show_warning(self, "无法读取下载目标", str(target), detail=describe(exc))
                return None
            if info is None and len(items) == 1:
                continue
            directory = info is not None and target.is_dir()
            existing = "当前目录下没有这个文件。同批构建使用了相同的名称。"
            if info is not None:
                modified = datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                existing = f"已有文件  {info.st_size:,} 字节  ·  修改于 {modified}"
                if target.is_symlink():
                    existing = "目标是符号链接。"
                if directory:
                    existing = "同名目标是文件夹，只能跳过。"
            if len(items) > 1:
                dialog = CandidateConflictDialog(self, target, existing, items,
                                                 existing=info is not None, directory=directory)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return None
                chosen = indexes[dialog.choice] if dialog.choice is not None else None
            else:
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Question)
                box.setWindowTitle("同名文件")
                box.setTextFormat(Qt.TextFormat.PlainText)
                box.setText(f"{target.name}\n{existing}\n\n待下载  {_candidate_text(items[0])}")
                item = items[0]
                box.setDetailedText(f"{target}\n{item.file.url}\nSHA-1 "
                                    + (item.file.hashes.get("sha1") or "未知"))
                skip = box.addButton("跳过", QMessageBox.ButtonRole.NoRole)
                cancel = box.addButton("取消本次下载", QMessageBox.ButtonRole.RejectRole)
                replace = None if directory else box.addButton("覆盖", QMessageBox.ButtonRole.AcceptRole)
                box.setDefaultButton(skip)
                box.setEscapeButton(cancel)
                box.exec()
                clicked = box.clickedButton()
                if clicked is None or clicked is cancel:
                    return None
                chosen = indexes[0] if clicked is replace else None
            selected.update((index, index == chosen) for index in indexes)
            if chosen is not None and info is not None:
                overwrite[self._prep.plan.items[chosen].target.name] = True
        return selected, overwrite

    def _on_go(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.btn_go.setEnabled(False)
            self.lb_progress.setText("正在取消……（已下好的文件会保留）")
            return
        if self._prep is None:
            return
        choice = self._confirm_conflicts()
        if choice is None:
            return
        selected, overwrite = choice
        self._worker = DownloadWorker(self._backend, self._prep, selected, overwrite, self)
        self._worker.progressed.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._worker.deleteLater)
        self.btn_pick.setEnabled(False)
        self.ck_prerelease.setEnabled(False)
        self.table.setEnabled(False)
        # ⚠️ 用**有界**进度条（0..文件总数）而不是循环条：
        # 循环条给不出"还剩多少"的信息，而下载恰恰是用户最想知道进度的时候。
        # 下载是按文件并发的，回调给的就是 (已完成, 总数, 文件名)，直接对应。
        total = len(self._prep.plan.items) if self._prep else 0
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(0)
        self.btn_go.setText("取消")
        self.lb_progress.setText(f"正在下载 0/{total}……")
        self._worker.start()

    def _on_progress(self, done: int, total: int, name: str) -> None:
        """逐个文件推进（与检查界面同一套观感）。"""
        if not self.btn_go.isEnabled():
            return
        if self.bar.maximum() != total:
            self.bar.setRange(0, total)
        self.bar.setValue(done)
        self.lb_progress.setText(f"正在下载 {done}/{total}：{name}")

    def _on_done(self, outcome) -> None:
        s = outcome.summary
        self.bar.setValue(s.ok + s.skipped + s.failed)
        # ⚠️ 用 skipped_total 而不是 skipped：准备屏明确列了「N 个模组没有可下载的 jar /
        # 没有可用版本」，汇总若用另一个数就会对不上（子代理 review 时抓到的）。
        # 界面上两个数对不上，用户不会认为是我们口径不同，只会认为程序算错了。
        skip_total = s.skipped_total          # 计算属性：含计划期跳过，与准备屏的数字对得上
        parts = [f"成功 {s.ok} 个", f"跳过 {skip_total} 个"]
        if s.failed:
            parts.append(f"失败 {s.failed} 个")
        if s.cancelled:
            parts.append("（已取消，已下好的保留）")
        self.lb_progress.setText(
            "下载完成：" + "，".join(parts)
            + f"　共 {_size_mb(s.bytes_total)}　用时 {s.elapsed:.0f} 秒"
            + f"　目录：{s.target_dir}")
        target_appeared = [name for name, reason in s.skipped_rows
                           if reason == SKIP_TARGET_APPEARED]
        if target_appeared and not self._close_pending:
            show_warning(self, "下载时发现新的同名文件",
                         "已保留这些文件。再次点击「开始下载」可以选择跳过或覆盖。",
                         detail="\n".join(target_appeared))
        # 只列**真正的下载失败**（failure_rows 是 3 元组，行数与 failed 相等）——
        # 用 failed_items 会把计划期跳过的条目也算进来，数字就对不上了
        if s.failure_rows and not self._close_pending:
            # ⚠️ 必须连**原因**一起给。只列文件名的话用户既不知道怎么办，
            # 也没法向我们反馈到底出了什么事（收到过"24 个失败"却无从下手）。
            lines = []
            for name, key, detail in s.failure_rows[:10]:
                try:
                    why = t(key, detail=detail)
                except Exception:
                    why = str(detail or key)
                lines.append(f"    · {name}\n        {why}")
            more = "" if len(s.failure_rows) <= 10 else f"\n    …… 还有 {len(s.failure_rows) - 10} 个"
            # 全是网络错误时给一条**可操作**的排查建议：
            # 「检查能成功但下载全失败」在国内是很常见的现象 —— 检查走 api.modrinth.com，
            # 下载走 cdn.modrinth.com，是**两个不同的域名**，后者经常连不上。
            # 只说「下载失败」用户无从下手，等于把问题丢回给他。
            net_only = all(row[1] == "download.error.net" for row in s.failure_rows)
            # 主文案只留"发生了什么 + 怎么办"两句话；逐条原因与排查建议进「详细信息」。
            # 之前把这一切塞进主文案，弹出来占满整屏，用户根本读不完。
            head = f"{s.failed} 个文件没能下载。请查看详细信息。"
            if net_only:
                head += "\n\n可检查 Modrinth CDN 的连接或代理设置，再重试失败项。"
            detail = "\n".join(lines) + more
            show_warning(self, "有文件没下成功", head, detail=detail)

    def _on_failed(self, message: str) -> None:
        if self._close_pending:
            return
        self.lb_progress.setText("下载失败")
        show_warning(self, "下载失败",
                     "下载任务中断。请检查目标文件夹中的结果和下方的详细信息。",
                     detail=message)

    def _on_finished(self) -> None:
        self._worker = None
        if self._close_pending:
            super().reject()
            return
        self.btn_go.setText("开始下载")
        self.btn_go.setEnabled(bool(self._prep and self._prep.plan.items))
        self.btn_pick.setEnabled(True)
        self.ck_prerelease.setEnabled(self._dir is not None)
        self.table.setEnabled(True)

    def done(self, status: int) -> None:
        if self._worker is not None:
            self._close_pending = True
            self._on_go()
            return
        super().done(status)


__all__ = ["DownloadDialog"]
