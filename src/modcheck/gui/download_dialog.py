"""下载对话框（GUI 三期第二半）：把「建议的模组版本」下到指定文件夹。

流程刻意分成两步 —— **先给用户看清楚要下什么，再动手**：
    选目录 → prepare（只选品与查冲突，不写盘不建目录）→ 展示计划与冲突 → 确认 → 下载 → 汇总

判定与下载全部来自 core/downloader.py 与 flows/download_flow.py（与 CLI 同一套），
界面只负责展示与询问。
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QFileDialog, QHBoxLayout,
                             QHeaderView, QLabel, QMessageBox, QProgressBar, QPushButton,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from modcheck.gui import theme


def _size_mb(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB" if n else "—"


class DownloadWorker(QThread):
    """下载在后台跑；进度按"第几个文件"回报（单文件内部字节数由 core 统计）。"""

    progressed = pyqtSignal(int, int, str)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, backend, prep, overwrite, parent=None) -> None:
        super().__init__(parent)
        self._backend, self._prep, self._overwrite = backend, prep, overwrite
        self._stop = False

    def cancel(self) -> None:
        self._stop = True

    def run(self) -> None:                                   # noqa: D102
        try:
            outcome = self._backend.run_download(
                self._prep, overwrite=self._overwrite,
                on_progress=lambda d, t, n: self.progressed.emit(d, t, n),
                should_stop=lambda: self._stop)
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
        self._worker: DownloadWorker | None = None
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
            "只会下载 🟢 就绪与 🟡 需注意两类里建议你使用的那个版本；"
            "🔴 阻塞、🟠 仅存测试版、⚪ 未判定一律跳过。")
        self.lb_hint.setObjectName("sub")
        self.lb_hint.setWordWrap(True)
        outer.addWidget(self.lb_hint)

        row = QHBoxLayout()
        row.addWidget(QLabel("下载到"))
        self.ed_dir = QLabel("（未选择）")
        self.ed_dir.setObjectName("sub")
        row.addWidget(self.ed_dir, 1)
        pick = QPushButton("选择文件夹…")
        pick.clicked.connect(self._on_pick)
        row.addWidget(pick)
        outer.addLayout(row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["模组", "版本", "文件名", "大小", "覆盖"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        # 「覆盖」列必须给足宽度：ResizeToContents 算不出 QCheckBox 的"复选框+文字"宽度，
        # 实测会把「覆盖已有」截成「覆盖已…」（视觉评审发现）
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
        close.clicked.connect(self.accept)
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
        try:
            self._prep = self._backend.prepare_download(self._report, target)
        except Exception as exc:
            QMessageBox.warning(self, "准备失败", f"{type(exc).__name__}: {exc}")
            return
        self._fill()

    def _fill(self) -> None:
        prep = self._prep
        items = list(prep.plan.items)
        conflicts = {id(c) for c in prep.conflicts}
        self.table.setRowCount(0)
        self.table.setRowCount(len(items))
        for i, item in enumerate(items):
            entry = item.entry
            name = getattr(entry, "display_name", "") or entry.file_name or entry.key
            self.table.setItem(i, 0, QTableWidgetItem(str(name)))
            self.table.setItem(i, 1, QTableWidgetItem(item.version.version_number))
            self.table.setItem(i, 2, QTableWidgetItem(item.file.filename))
            self.table.setItem(i, 3, QTableWidgetItem(_size_mb(getattr(item.file, "size", 0))))
            if id(item) in conflicts:
                box = QCheckBox("覆盖已有")
                box.setChecked(False)          # 默认**不覆盖**：保守优先
                self.table.setCellWidget(i, 4, box)
            else:
                self.table.setItem(i, 4, QTableWidgetItem("—"))
        n_conflict = len(prep.conflicts)
        skipped_bits = []
        if prep.no_jar:
            skipped_bits.append(f"{len(prep.no_jar)} 个模组没有可下载的 jar")
        if prep.no_version:
            skipped_bits.append(f"{len(prep.no_version)} 个模组在目标版本上没有可用版本")
        if prep.extra_files:
            skipped_bits.append(f"{prep.extra_files} 个模组另有附属文件（不下）")
        self.lb_skip.setText("；".join(skipped_bits) or "")
        self.lb_progress.setText(
            f"将下载 {len(items)} 个文件" + (f"，其中 {n_conflict} 个会覆盖已有文件" if n_conflict else ""))
        self.btn_go.setEnabled(bool(items))

    # ---------------------------------------------------------------- 下载
    def _overwrite_map(self) -> dict:
        """冲突文件 → 是否覆盖。未勾选的走「跳过」，不是「报错」。

        ⚠️ 键必须是**目标文件名**（core 的 overwrite_key 就是这么定的），
        写成完整路径键就对不上，用户勾的「不覆盖」会被静默忽略（实测踩过）。
        """
        prep, out = self._prep, {}
        conflicts = {id(c) for c in prep.conflicts}
        for i, item in enumerate(prep.plan.items):
            if id(item) not in conflicts:
                continue
            widget = self.table.cellWidget(i, 4)
            out[item.target.name] = bool(widget and widget.isChecked())
        return out

    def _on_go(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.lb_progress.setText("正在取消……（已下好的文件会保留）")
            return
        self._worker = DownloadWorker(self._backend, self._prep, self._overwrite_map(), self)
        self._worker.progressed.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_finished)
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
        if self.bar.maximum() != total:
            self.bar.setRange(0, total)
        self.bar.setValue(done)
        self.lb_progress.setText(f"正在下载 {done}/{total}：{name}")

    def _on_done(self, outcome) -> None:
        s = outcome.summary
        # ⚠️ 用 skipped_total 而不是 skipped：准备屏明确列了「N 个模组没有可下载的 jar /
        # 没有可用版本」，汇总若用另一个数就会对不上（子代理 review 时抓到的）。
        # 界面上两个数对不上，用户不会认为是我们口径不同，只会认为程序算错了。
        skip_total = s.skipped_total          # 计算属性：含计划期跳过，与准备屏的数字对得上
        parts = [f"成功 {s.ok} 个", f"跳过 {skip_total} 个"]
        if s.failed:
            parts.append(f"**失败 {s.failed} 个**")
        if s.cancelled:
            parts.append("（已取消，已下好的保留）")
        self.lb_progress.setText(
            "下载完成：" + "，".join(parts)
            + f"　共 {_size_mb(s.bytes_total)}　用时 {s.elapsed:.0f} 秒"
            + f"　目录：{s.target_dir}")
        # 只列**真正的下载失败**（failure_rows 是 3 元组，行数与 failed 相等）——
        # 用 failed_items 会把计划期跳过的条目也算进来，数字就对不上了
        if s.failure_rows:
            # ⚠️ 必须连**原因**一起给。只列文件名的话用户既不知道怎么办，
            # 也没法向我们反馈到底出了什么事（收到过"24 个失败"却无从下手）。
            from modcheck.i18n import t

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
            tip = ("\n\n排查建议：\n"
                   "  · 如果「检查」能正常出结果、只有下载失败，通常是下载服务器\n"
                   "    （cdn.modrinth.com，与检查用的接口不是同一个域名）连不上。\n"
                   "  · 可在「设置 → 代理」里填一个可用代理后重试。\n"
                   "  · 也可以按上面的文件名自行到 Modrinth 页面手动下载。") if net_only else ""
            QMessageBox.warning(self, "有文件没下成功",
                                f"以下 {s.failed} 个文件下载失败：\n\n" + "\n".join(lines) + more +
                                tip + "\n\n可以稍后重试（已成功的不会重复下载）。")

    def _on_failed(self, message: str) -> None:
        self.lb_progress.setText("下载失败")
        QMessageBox.warning(self, "下载失败", message)

    def _on_finished(self) -> None:
        self._worker = None
        self.btn_go.setText("开始下载")
        self.bar.setRange(0, 1)


__all__ = ["DownloadDialog"]
