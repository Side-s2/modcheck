"""GUI 主窗口：检查 + 结果展示（一期）。

设计要点
--------
* **不卡界面**：检查跑在 QThread 里，进度用信号回传，随时可取消。
* **不重复实现流程**：真正的检查逻辑从外部注入（CheckService），
  CLI 与 GUI 共用 modcheck.flows 的同一套流程。
* **状态配色与 CLI 一致**：见 theme.STATUS_COLOR。
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout,
                             QHeaderView, QLabel, QMainWindow, QMessageBox, QProgressBar,
                             QPushButton, QTabBar, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget)

from modcheck.gui import theme


@dataclass(frozen=True, slots=True)
class Row:
    """表格里的一行（GUI 自己的展示模型，与 core 解耦）。"""
    name: str
    status: str            # blocked / prerelease / degraded / unknown / ready / ignored
    version: str
    date: str
    reason: str = ""
    available: str = ""


class CheckService(Protocol):
    """GUI 需要的全部后端能力。CLI 侧由 flows 实现，测试里用假实现。"""

    def profiles(self) -> Sequence[tuple[str, int]]: ...
    def versions(self) -> Sequence[str]: ...
    def run(self, profile: str, mc: str, loader: str,
            on_progress: Callable[[int, int, str], None],
            should_stop: Callable[[], bool]) -> tuple[str, list[Row]]: ...


class CheckWorker(QThread):
    """把检查放到后台线程 —— Qt 要求 UI 只能在主线程更新。"""

    progressed = pyqtSignal(int, int, str)
    done = pyqtSignal(str, list)          # (结论行, 行列表)
    failed = pyqtSignal(str)

    def __init__(self, service: CheckService, profile: str, mc: str, loader: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._profile, self._mc, self._loader = profile, mc, loader
        self._stop = False

    def cancel(self) -> None:
        self._stop = True

    def run(self) -> None:                                  # noqa: D102
        try:
            verdict, rows = self._service.run(
                self._profile, self._mc, self._loader,
                on_progress=lambda d, t, n: self.progressed.emit(d, t, n),
                should_stop=lambda: self._stop)
            self.done.emit(verdict, list(rows))
        except Exception as exc:                            # 任何失败都要让用户看见
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class MainWindow(QMainWindow):
    """主窗口。"""

    def __init__(self, service: CheckService) -> None:
        super().__init__()
        self._service = service
        self._worker: CheckWorker | None = None
        self._rows: list[Row] = []
        self.setWindowTitle("Minecraft 模组兼容性检查")
        self.resize(1180, 900)
        self._build()

    # ---------------------------------------------------------------- 构建
    def _card(self) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("card")
        lay = QVBoxLayout(frame)
        return frame, lay

    def _build_menu(self) -> None:
        """菜单栏：清单管理、设置、帮助。二期把前两项接上。"""
        bar = self.menuBar()
        manage = bar.addMenu("清单(&P)")
        manage.addAction("扫描 mods 文件夹…", self._open_scan)
        manage.addAction("管理模组清单…", self._open_profiles)
        manage.addAction("刷新清单列表", self._reload_profiles)
        settings = bar.addMenu("设置(&S)")
        settings.addAction("打开设置…", self._open_settings)
        help_menu = bar.addMenu("帮助(&H)")
        help_menu.addAction("关于", self._show_about)

    def _open_scan(self) -> None:
        from modcheck.gui.scan_dialog import ScanDialog

        ScanDialog(self._service, self).exec()
        self._reload_profiles()

    def _open_profiles(self) -> None:
        from modcheck.gui.profiles_dialog import ProfilesDialog

        ProfilesDialog(self._service, self).exec()
        self._reload_profiles()

    def _open_settings(self) -> None:
        from modcheck.gui.settings_dialog import SettingsDialog

        SettingsDialog(self._service, self).exec()

    def _show_about(self) -> None:
        """关于框：版本、数据来源、许可证 —— 用户与分发者都需要看到这三样。"""
        from modcheck import __version__

        QMessageBox.about(
            self, "关于 modcheck",
            f"<b>Minecraft 模组兼容性检查 {__version__}</b><br><br>"
            "数据来自 <b>Modrinth</b> 与 <b>Mojang 官方版本清单</b>。<br>"
            "本程序<b>不重新分发任何模组文件</b>：下载的是 Modrinth 官方 CDN 直链。<br><br>"
            "以 <b>GPL-3.0</b> 发布（因图形界面使用 PyQt6，其许可证为 GPL v3）。<br>"
            "详见随附的 LICENSE 与 THIRD_PARTY_NOTICES.md。<br><br>"
            "<b>DEVELOPED BY SIDE_LF</b>")

    def _reload_profiles(self) -> None:
        """重新读清单列表并保持当前选择。"""
        current = self._profile_name()
        items = [f"{n}（{c} 个模组）" for n, c in self._service.profiles()]
        self.cb_profile.blockSignals(True)
        self.cb_profile.clear()
        self.cb_profile.addItems(items or ["（无）"])
        self.cb_profile.blockSignals(False)
        if current:
            for i, text in enumerate(items):
                if text.startswith(current):
                    self.cb_profile.setCurrentIndex(i)
                    break
        self.btn_go.setEnabled(bool(items))

    def _build(self) -> None:
        self._build_menu()
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(14)

        # ---- 顶部：标题 + 控制条 + 进度 ----
        head, hl = self._card()
        hl.setContentsMargins(18, 16, 18, 16)
        hl.setSpacing(12)
        title = QLabel("Minecraft 模组兼容性检查")
        title.setObjectName("title")
        sub = QLabel("检查你的模组是否支持目标游戏版本 —— 数据来自 Modrinth")
        sub.setObjectName("sub")
        hl.addWidget(title)
        hl.addWidget(sub)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.cb_profile = self._combo(row, "模组清单",
                                      [f"{n}（{c} 个模组）" for n, c in self._service.profiles()])
        self.cb_mc = self._combo(row, "目标版本", list(self._service.versions()))
        self.cb_loader = self._combo(row, "服务端加载器", ["Fabric", "NeoForge", "Forge"])
        row.addStretch(1)
        self.btn_go = QPushButton("开始检查")
        self.btn_go.setObjectName("primary")
        self.btn_go.clicked.connect(self._on_start)
        row.addWidget(self.btn_go, alignment=Qt.AlignmentFlag.AlignBottom)
        hl.addLayout(row)

        pl = QHBoxLayout()
        self.lb_progress = QLabel("尚未开始")
        self.lb_eta = QLabel("")
        pl.addWidget(self.lb_progress)
        pl.addStretch(1)
        pl.addWidget(self.lb_eta)
        hl.addLayout(pl)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        hl.addWidget(self.bar)
        outer.addWidget(head)

        # ---- 结论条 ----
        verdict_card, vl = self._card()
        vl.setContentsMargins(4, 4, 4, 4)
        self.lb_verdict = QLabel("选择清单与目标版本后，点击「开始检查」")
        self.lb_verdict.setObjectName("verdict")
        self.lb_verdict.setStyleSheet(f"color:{theme.MUTED};")
        vl.addWidget(self.lb_verdict)
        outer.addWidget(verdict_card)
        if not self._service.profiles():
            # 空状态要说清"下一步做什么"，而不是留一个空表格让人发呆
            self.lb_verdict.setText("还没有模组清单。先用命令行建立一份："
                                    "modcheck scan \"<mods 文件夹>\" --profile 服务器A")
            self.btn_go.setEnabled(False)

        # ---- 分页签 + 表格 ----
        body, bl = self._card()
        bl.setContentsMargins(14, 12, 14, 14)
        bl.setSpacing(10)
        # 分页签是**筛选器**，不是页面容器：
        # ⚠️ 一开始用 QTabWidget 并把表格当其中一页，结果重建页签时 removeTab 把表格控件
        #    自己删掉了 —— 表现是"表格一行都不显示"。改用裸 QTabBar + 唯一一个表格。
        self.tabbar = QTabBar()
        self.tabbar.setDrawBase(False)        # 不画底部那条基线，贴合卡片风格
        self.tabbar.setExpanding(False)       # 页签按内容宽度，不平均分配
        self.tabbar.currentChanged.connect(self._on_tab_changed)
        bl.addWidget(self.tabbar)
        self.table = self._make_table()
        bl.addWidget(self.table, 1)
        outer.addWidget(body, 1)

        # ---- 详情 ----
        # 详情卡**默认隐藏**：没选中行时它只是一块空白，白占表格的高度（实测看起来像坏了）
        self.detail_card, dl = self._card()
        dl.setContentsMargins(16, 12, 16, 12)
        dl.setSpacing(4)
        self.lb_detail_title = QLabel("")
        self.lb_detail_title.setStyleSheet("font-weight:600;")
        self.lb_detail_body = QLabel("")
        self.lb_detail_body.setWordWrap(True)
        dl.addWidget(self.lb_detail_title)
        dl.addWidget(self.lb_detail_body)
        self.detail_card.setVisible(False)
        outer.addWidget(self.detail_card)

        # ---- 底部 ----
        foot = QHBoxLayout()
        # 下载按钮：**必须在一次检查之后才能用**（它需要那份报告才知道下什么版本）
        self.btn_download = QPushButton("下载建议版本…")
        self.btn_download.setEnabled(False)
        self.btn_download.clicked.connect(self._on_download)
        foot.addWidget(self.btn_download)
        self.btn_json = QPushButton("导出 JSON")
        self.btn_md = QPushButton("导出 Markdown")
        self.btn_copy = QPushButton("复制重跑命令")
        self.btn_json.clicked.connect(lambda: self._on_export("json"))
        self.btn_md.clicked.connect(lambda: self._on_export("md"))
        self.btn_copy.clicked.connect(self._on_copy_command)
        for b in (self.btn_json, self.btn_md, self.btn_copy):
            b.setEnabled(False)
            foot.addWidget(b)
        foot.addStretch(1)
        self.lb_status = QLabel("")
        self.lb_status.setObjectName("sub")
        foot.addWidget(self.lb_status)
        outer.addLayout(foot)

    def _combo(self, row: QHBoxLayout, caption: str, items: Sequence[str]) -> QComboBox:
        box = QVBoxLayout()
        box.setSpacing(5)
        cap = QLabel(caption)
        cap.setObjectName("sub")
        cb = QComboBox()
        cb.addItems(list(items) or ["（无）"])
        box.addWidget(cap)
        box.addWidget(cb)
        row.addLayout(box)
        return cb

    def _make_table(self) -> QTableWidget:
        tbl = QTableWidget(0, 4)
        tbl.setHorizontalHeaderLabels(["模组", "状态", "版本", "发布日期"])
        tbl.verticalHeader().setVisible(False)
        tbl.setShowGrid(False)
        tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        # 按像素滚动：整行滚动时最后一行不会被切成一半（默认按行滚动会留半行）
        tbl.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        hh = tbl.horizontalHeader()
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        tbl.setColumnWidth(0, 300)
        tbl.setColumnWidth(1, 180)
        tbl.setColumnWidth(3, 130)
        tbl.itemSelectionChanged.connect(self._on_row_selected)
        return tbl

    # ---------------------------------------------------------------- 交互
    def _on_download(self) -> None:
        """打开下载对话框。用最近一次检查的报告决定"下哪些版本"。"""
        report = getattr(self._service, "last_report", None)
        if report is None:
            QMessageBox.information(self, "先跑一次检查",
                                   "下载建议版本需要先有一次检查结果 —— 请先点「开始检查」。")
            return
        from modcheck.gui.download_dialog import DownloadDialog

        DownloadDialog(self._service, report, self).exec()

    def _on_export(self, fmt: str) -> None:
        """导出报告 —— 走的是 flows.export，**与 CLI 导出同一份实现**（文件逐字节相同）。"""
        exporter = getattr(self._service, "export_to", None)
        if exporter is None:
            return
        default = self._service.export_default_name(fmt)      # type: ignore[attr-defined]
        caption = {"json": "导出 JSON", "md": "导出 Markdown", "csv": "导出 CSV"}.get(fmt, "导出")
        pattern = {"json": "JSON (*.json)", "md": "Markdown (*.md)", "csv": "CSV (*.csv)"}[fmt]
        path, _ = QFileDialog.getSaveFileName(self, caption, default, pattern)
        if not path:
            return                                    # 用户取消：什么都不做，不报错
        try:
            exporter(path, fmt)
            self.lb_status.setText("已导出：" + path)
        except Exception as exc:                      # 磁盘满/无权限：要让用户看见
            QMessageBox.warning(self, "导出失败", f"{type(exc).__name__}: {exc}")

    def _on_copy_command(self) -> None:
        """把等价的重跑命令复制到剪贴板 —— 让用户能在终端里复现同一次检查。"""
        cmd = (f"modcheck check --profile {self._profile_name()} "
               f"--mc {self.cb_mc.currentText()} --loader {self.cb_loader.currentText().lower()}")
        QApplication.clipboard().setText(cmd)
        self.lb_status.setText("已复制：" + cmd)

    def _profile_name(self) -> str:
        return self.cb_profile.currentText().split("（")[0]

    def _on_start(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.lb_progress.setText("正在取消……")
            return
        profile = self._profile_name()
        self._worker = CheckWorker(self._service, profile, self.cb_mc.currentText(),
                                   self.cb_loader.currentText(), self)
        self._worker.progressed.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_thread_finished)
        self.bar.setRange(0, 0)                 # 未知总数时显示忙碌动画
        self.btn_go.setText("取消")
        self.lb_progress.setText("正在准备……")
        self.lb_eta.setText("")
        self._worker.start()

    def _on_progress(self, done: int, total: int, name: str) -> None:
        if self.bar.maximum() != total:
            self.bar.setRange(0, total)
        self.bar.setValue(done)
        self.lb_progress.setText(f"正在检查 {done}/{total}：{name}")

    def _on_done(self, verdict: str, rows: list) -> None:
        self._rows = list(rows)
        self._render(verdict)

    def _on_failed(self, message: str) -> None:
        self.lb_verdict.setText("✗ 检查失败：" + message)
        self.lb_verdict.setStyleSheet(f"color:{theme.STATUS_COLOR['blocked']};")
        self.lb_progress.setText("已中止")

    def _on_thread_finished(self) -> None:
        self._worker = None
        self.btn_go.setText("开始检查")
        self.bar.setRange(0, 1)
        self.bar.setValue(1 if self._rows else 0)

    # ---------------------------------------------------------------- 渲染
    def _render(self, verdict: str) -> None:
        groups: dict[str, list[Row]] = {}
        for r in self._rows:
            groups.setdefault(r.status, []).append(r)
        order = ["blocked", "prerelease", "degraded", "unknown", "ready", "ignored"]
        color = theme.STATUS_COLOR["ready"] if not groups.get("blocked") else theme.STATUS_COLOR["blocked"]
        self.lb_verdict.setText(verdict)
        self.lb_verdict.setStyleSheet(f"color:{color};")

        # 重建筛选页签（全部 + 每个非空分组）；表格本身不动
        self.tabbar.blockSignals(True)
        while self.tabbar.count():
            self.tabbar.removeTab(0)
        self._pages: list[tuple[str, list[Row]]] = [("", self._rows)]
        self._add_page("全部 " + str(len(self._rows)), "", self._rows)
        for st in order:
            if groups.get(st):
                self._pages.append((st, groups[st]))
                self._add_page(theme.STATUS_LABEL[st] + " " + str(len(groups[st])), st, groups[st])
        self.tabbar.blockSignals(False)
        self.tabbar.setCurrentIndex(0)
        self._fill(self._rows)
        self.lb_progress.setText(f"检查完成，共 {len(self._rows)} 个模组")
        self.lb_eta.setText("")
        for b in (self.btn_json, self.btn_md, self.btn_copy, self.btn_download):
            b.setEnabled(True)

    def _add_page(self, text: str, status: str, rows: list[Row]) -> None:
        """加一个筛选页签（status 为空串表示"全部"）。"""
        idx = self.tabbar.addTab("")
        self.tabbar.setTabButton(idx, QTabBar.ButtonPosition.LeftSide,
                                 theme.tab_widget(text, status or None))

    def _on_tab_changed(self, index: int) -> None:
        pages = getattr(self, "_pages", None)
        if pages and 0 <= index < len(pages):
            self._fill(pages[index][1])

    def _fill(self, rows: list[Row]) -> None:
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(r.name))
            self.table.setCellWidget(i, 1, theme.status_chip(r.status))
            self.table.setItem(i, 2, QTableWidgetItem(r.version))
            self.table.setItem(i, 3, QTableWidgetItem(r.date))
            self.table.setRowHeight(i, 40)

    def _on_row_selected(self) -> None:
        items = self.table.selectedItems()
        if not items:
            self.detail_card.setVisible(False)
            return
        page = getattr(self, "_pages", None)
        rows = page[self.tabbar.currentIndex()][1] if page else self._rows
        r = self.table.currentRow()
        row = rows[r] if 0 <= r < len(rows) else None
        if row is None:
            return
        self.detail_card.setVisible(True)
        self.lb_detail_title.setText(f"{row.name}　·　{theme.STATUS_LABEL.get(row.status, '')}")
        parts = []
        if row.reason:
            parts.append("原因：" + row.reason)
        if row.available:
            parts.append("可用：" + row.available)
        self.lb_detail_body.setText("\n".join(parts) or "（无更多信息）")


__all__ = ["MainWindow", "CheckWorker", "CheckService", "Row"]
