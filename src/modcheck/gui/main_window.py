"""GUI 主窗口：检查 + 结果展示（一期）。

设计要点
--------
* **不卡界面**：检查跑在 QThread 里，进度用信号回传，随时可取消。
* **不重复实现流程**：真正的检查逻辑从外部注入（CheckService），
  CLI 与 GUI 共用 modcheck.flows 的同一套流程。
* **状态配色与 CLI 一致**：见 theme.STATUS_COLOR。
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Callable, Protocol, Sequence

from PyQt6.QtCore import QEvent, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout,
                             QHeaderView, QInputDialog, QLabel, QMainWindow, QMessageBox,
                             QProgressBar,
                             QPushButton, QSizePolicy, QTabBar, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget)

from modcheck.core.mcversion import is_release_like, validate_target_version
from modcheck.core.models import Settings, Status
from modcheck.core.report import Report
from modcheck.errors import ConfigError
from modcheck.gui import theme
from modcheck.gui.dialogs import choose_json_output, describe, show_warning

#: 目标版本下拉里的「自定义…」条目 —— 选它才弹窗手输
CUSTOM_MC = "自定义…"
CHOOSE_MC = "（请选择版本）"
CHECK_HINT = "选择清单与目标版本后，点击「开始检查」"
EMPTY_PROFILES = "还没有模组清单。请在「清单」菜单扫描 mods 文件夹或导入已有清单。"


@dataclass(frozen=True, slots=True)
class Row:
    """表格里的一行（GUI 自己的展示模型，与 core 解耦）。"""
    name: str
    status: str            # blocked / prerelease / degraded / unknown / ready / ignored
    version: str
    date: str
    reason: str = ""
    available: str = ""
    mod_ids: tuple[str, ...] = ()


class CheckService(Protocol):
    """主窗口所需的检查接口。"""

    last_report: Report | None

    def load_settings(self) -> Settings: ...
    def profiles(self) -> Sequence[tuple[str, int]]: ...
    def versions(self, should_stop: Callable[[], bool] | None = None) -> Sequence[str]: ...
    def run(self, profile: str, mc: str, loader: str,
            on_progress: Callable[[int, int, str], None],
            should_stop: Callable[[], bool], *, refresh: bool = False) -> list[Row]: ...
    def export_default_name(self) -> str: ...
    def export_to(self, path: str) -> object: ...


class CheckWorker(QThread):
    """把检查放到后台线程 —— Qt 要求 UI 只能在主线程更新。"""

    progressed = pyqtSignal(int, int, str)
    done = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, service: CheckService, profile: str, mc: str, loader: str,
                 parent: QWidget | None = None, *, refresh: bool = False) -> None:
        super().__init__(parent)
        self._service = service
        self._profile, self._mc, self._loader = profile, mc, loader
        self._stop = Event()
        self._refresh = refresh

    def cancel(self) -> None:
        self._stop.set()

    def run(self) -> None:                                  # noqa: D102
        try:
            rows = self._service.run(
                self._profile, self._mc, self._loader,
                on_progress=lambda d, t, n: self.progressed.emit(d, t, n),
                should_stop=self._stop.is_set, refresh=self._refresh)
            self.done.emit(rows)
        except Exception as exc:                            # 任何失败都要让用户看见
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class VersionsWorker(QThread):
    loaded = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, service: CheckService, parent: QWidget) -> None:
        super().__init__(parent)
        self._service = service

    def run(self) -> None:
        try:
            versions = list(self._service.versions(should_stop=self.isInterruptionRequested))
            if not versions:
                raise ValueError("官方版本列表为空。")
        except Exception as exc:
            self.failed.emit(describe(exc))
        else:
            self.loaded.emit(versions)


class _CheckProgressLabel(QLabel):
    """检查摘要占一行。空间不足时保留完整的悬浮提示。"""

    def __init__(self) -> None:
        super().__init__()
        self._summary: str | None = None
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.show_message(CHECK_HINT)

    def show_message(self, text: str) -> None:
        self._summary = None
        self.setWordWrap(True)
        self.setText(text)
        self.setToolTip("")
        self.setAccessibleName("")

    def show_summary(self, text: str, warnings: Sequence[str]) -> None:
        self._summary = " ".join(text.splitlines())
        self.setWordWrap(False)
        self.setToolTip("\n".join((self._summary, *warnings)))
        self.setAccessibleName(self._summary)
        self._fit_summary()

    def _fit_summary(self) -> None:
        if self._summary is not None:
            self.setText(self.fontMetrics().elidedText(
                self._summary, Qt.TextElideMode.ElideRight, self.contentsRect().width()))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_summary()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._fit_summary()


class MainWindow(QMainWindow):
    """主窗口。"""

    def __init__(self, service: CheckService) -> None:
        super().__init__()
        self._service = service
        self._worker: CheckWorker | None = None
        self._versions_worker: VersionsWorker | None = None
        self._close_pending = False
        self._known_mc: list[str] = []
        self._selected_mc = ""
        self._report: Report | None = None
        self._rows: list[Row] = []
        self.setWindowTitle("Minecraft 模组兼容性检查")
        self.resize(1180, 900)
        self._build()
        self._apply_defaults()
        self._reload_profiles()
        QTimer.singleShot(0, self._load_versions)

    # ---------------------------------------------------------------- 构建
    def _card(self) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("card")
        lay = QVBoxLayout(frame)
        return frame, lay

    def _build_menu(self) -> None:
        """菜单栏：清单管理、设置、帮助。二期把前两项接上。"""
        bar = self.menuBar()
        manage = theme.RoundedMenu("清单(&P)", bar)
        bar.addMenu(manage)
        manage.addAction("扫描 mods 文件夹…", self._open_scan)
        manage.addAction("管理模组清单…", self._open_profiles)
        manage.addAction("刷新清单列表", self._refresh_profiles)
        settings = theme.RoundedMenu("设置(&S)", bar)
        bar.addMenu(settings)
        settings.addAction("打开设置…", self._open_settings)
        self.reload_versions = settings.addAction("重新加载游戏版本", self._load_versions)
        help_menu = theme.RoundedMenu("帮助(&H)", bar)
        bar.addMenu(help_menu)
        help_menu.addAction("使用教程", self._show_tutorial)
        help_menu.addAction("关于", self._show_about)

    def _open_scan(self) -> None:
        from modcheck.gui.scan_dialog import ScanDialog

        if ScanDialog(self._service, self).exec():
            self._discard_result()
        self._reload_profiles()

    def _open_profiles(self) -> None:
        from modcheck.gui.profiles_dialog import ProfilesDialog

        dialog = ProfilesDialog(self._service, self)
        dialog.profiles_changed.connect(self._discard_result)
        dialog.exec()
        self._reload_profiles()

    def _open_settings(self) -> None:
        from modcheck.gui.settings_dialog import SettingsDialog

        before = self._service.load_settings()
        if SettingsDialog(self._service, self, known_versions=self._known_mc).exec():
            current = self._service.load_settings()
            if before.theme != current.theme:
                theme.apply_theme(QApplication.instance(), current.theme)
            self._apply_defaults(current, before)
            if before.proxy != current.proxy or not self._known_mc:
                self._load_versions()

    def _apply_defaults(self, settings: Settings | None = None, before: Settings | None = None) -> None:
        settings = settings if settings is not None else self._service.load_settings()
        if before is None or before.default_loader != settings.default_loader:
            self.cb_loader.setCurrentText(settings.default_loader.display_name)
        if before is not None and before.default_mc_version == settings.default_mc_version:
            return
        version = settings.default_mc_version or (self._known_mc[0] if self._known_mc else "")
        if version and is_release_like(version) and (not self._known_mc or version in self._known_mc):
            index = self.cb_mc.findText(version)
            if index < 0:
                self.cb_mc.insertItem(0, version)
                index = 0
            self.cb_mc.setCurrentIndex(index)
            self._selected_mc = version
        elif before is not None and settings.default_mc_version is None:
            self._selected_mc = ""
            self._populate_versions()
        self._on_target_changed()

    def _show_tutorial(self) -> None:
        from modcheck.gui.tutorial_dialog import TutorialDialog

        TutorialDialog(self).exec()

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
        try:
            profiles = self._service.profiles()
        except (OSError, ValueError) as exc:
            profiles = ()
            self.lb_status.setText(f"无法读取清单目录：{describe(exc)}")
        self.cb_profile.blockSignals(True)
        self.cb_profile.clear()
        for name, count in profiles:
            self.cb_profile.addItem(f"{name}（{count} 个模组）", name)
        if not profiles:
            self.cb_profile.addItem("（无清单）")
        index = self.cb_profile.findData(current)
        self.cb_profile.setCurrentIndex(max(index, 0))
        self.cb_profile.blockSignals(False)
        self.cb_profile.setEnabled(bool(profiles))
        if not profiles:
            self.lb_progress.show_message(EMPTY_PROFILES)
        elif self.lb_progress.text() == EMPTY_PROFILES:
            self.lb_progress.show_message(CHECK_HINT)
        self._on_target_changed()

    def _refresh_profiles(self) -> None:
        self._discard_result()
        self._reload_profiles()

    def _load_versions(self) -> None:
        if self._close_pending or self._versions_worker is not None or self._worker is not None:
            return
        self.lb_status.setText("正在读取官方游戏版本…")
        self.reload_versions.setEnabled(False)
        self._versions_worker = VersionsWorker(self._service, self)
        self._versions_worker.loaded.connect(self._on_versions_loaded)
        self._versions_worker.failed.connect(self._on_versions_failed)
        self._versions_worker.finished.connect(self._on_versions_finished)
        self._versions_worker.finished.connect(self._versions_worker.deleteLater)
        self._versions_worker.start()

    def _on_versions_loaded(self, versions: list[str]) -> None:
        self._known_mc = versions
        self._populate_versions()
        self.lb_status.clear()
        self.lb_status.setToolTip("")

    def _populate_versions(self) -> None:
        visible = self._known_mc[:9] or [CHOOSE_MC]
        if self._selected_mc and self._selected_mc not in visible:
            visible.insert(0, self._selected_mc)
        self.cb_mc.blockSignals(True)
        self.cb_mc.clear()
        self.cb_mc.addItems(visible + [CUSTOM_MC])
        if CHOOSE_MC in visible:
            self.cb_mc.model().item(visible.index(CHOOSE_MC)).setEnabled(False)
        if self._selected_mc:
            self.cb_mc.setCurrentText(self._selected_mc)
        self.cb_mc.blockSignals(False)
        self._selected_mc = self._mc_name()
        self._on_target_changed()

    def _on_versions_failed(self, message: str) -> None:
        self.lb_status.setText("官方版本列表读取失败，可手动输入版本。")
        self.lb_status.setToolTip(message)

    def _on_versions_finished(self) -> None:
        self._versions_worker = None
        self.reload_versions.setEnabled(True)
        if self._close_pending and self._worker is None:
            self.close()

    def closeEvent(self, event) -> None:
        if self._versions_worker is not None or self._worker is not None:
            self._close_pending = True
            self.lb_status.setText("正在关闭…")
            self.centralWidget().setEnabled(False)
            self.menuBar().setEnabled(False)
            if self._versions_worker is not None:
                self._versions_worker.requestInterruption()
            if self._worker is not None:
                self._worker.cancel()
            event.ignore()
            return
        super().closeEvent(event)

    def _update_check_button(self) -> None:
        self.btn_go.setEnabled(self._worker is not None
                               or bool(self._profile_name() and self._mc_name()))

    def _on_target_changed(self) -> None:
        report = self._report
        if report is not None and (report.profile_name, report.mc_version, report.loader.display_name) != (
                self._profile_name(), self._mc_name(), self.cb_loader.currentText()):
            self._discard_result()
        self._update_check_button()

    def _discard_result(self) -> None:
        self._report = None
        self._rows.clear()
        self._pages = []
        self.table.setRowCount(0)
        while self.tabbar.count():
            self.tabbar.removeTab(0)
        self._update_report_buttons()
        if self._worker is None:
            self.lb_progress.show_message(CHECK_HINT if self._profile_name() else EMPTY_PROFILES)
            self.bar.setRange(0, 1)
            self.bar.setValue(0)

    def _update_report_buttons(self) -> None:
        report = self._report if self._worker is None else None
        self.btn_download.setEnabled(
            report is not None and not report.interrupted and any(
                report.groups.get(status) for status in (Status.READY, Status.DEGRADED, Status.PRERELEASE)))
        self.btn_json.setEnabled(report is not None)
        cached = report.cache_hits if report is not None else 0
        self.lb_cache.setText(f"本次检查使用了 {cached} 条缓存数据" if cached else "")
        self.lb_cache.setVisible(bool(cached))
        self.btn_recheck.setVisible(bool(cached))

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
        self.cb_profile = self._combo(row, "模组清单", [])
        # 目标版本：**常用的是从列表里选**（作者反馈：只让手输反而奇怪）。
        # 所以列最近 9 个 + 一个「自定义…」——选它才弹窗输入，并按官方全量清单校验。
        self.cb_mc = self._combo(row, "目标版本", [CHOOSE_MC, CUSTOM_MC])
        self.cb_mc.model().item(0).setEnabled(False)
        self.cb_mc.activated.connect(self._on_mc_activated)
        self.cb_loader = self._combo(row, "服务端加载器", ["Fabric", "NeoForge", "Forge"])
        row.addStretch(1)
        self.btn_go = QPushButton("开始检查")
        self.btn_go.setObjectName("primary")
        self.btn_go.clicked.connect(self._on_start)
        row.addWidget(self.btn_go, alignment=Qt.AlignmentFlag.AlignBottom)
        hl.addLayout(row)

        self.lb_progress = _CheckProgressLabel()
        hl.addWidget(self.lb_progress)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        hl.addWidget(self.bar)
        outer.addWidget(head)

        cache_row = QHBoxLayout()
        self.lb_cache = QLabel()
        self.lb_cache.setObjectName("cacheNotice")
        self.lb_cache.hide()
        cache_row.addWidget(self.lb_cache, 1)
        self.btn_recheck = QPushButton("立即联网重查")
        self.btn_recheck.setToolTip("用当前清单和目标重新检查，跳过本地缓存")
        self.btn_recheck.clicked.connect(lambda: self._on_start(refresh=True))
        self.btn_recheck.hide()
        cache_row.addWidget(self.btn_recheck)
        hl.addLayout(cache_row)

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

        # ---- 底部 ----
        foot = QHBoxLayout()
        # 下载按钮：**必须在一次检查之后才能用**（它需要那份报告才知道下什么版本）
        self.btn_download = QPushButton("下载建议版本…")
        self.btn_download.setEnabled(False)
        self.btn_download.clicked.connect(self._on_download)
        foot.addWidget(self.btn_download)
        self.btn_json = QPushButton("导出 JSON")
        self.btn_json.clicked.connect(self._on_export)
        self.btn_json.setEnabled(False)
        foot.addWidget(self.btn_json)
        foot.addStretch(1)
        self.lb_status = QLabel("")
        self.lb_status.setObjectName("sub")
        foot.addWidget(self.lb_status)
        outer.addLayout(foot)
        self.cb_profile.currentIndexChanged.connect(self._on_target_changed)
        self.cb_loader.currentIndexChanged.connect(self._on_target_changed)
        self.cb_mc.currentIndexChanged.connect(self._on_version_changed)

    def _on_version_changed(self) -> None:
        if self.cb_mc.currentText() != CUSTOM_MC:
            self._selected_mc = self._mc_name()
            self._on_target_changed()

    def _combo(self, row: QHBoxLayout, caption: str, items: Sequence[str]) -> QComboBox:
        box = QVBoxLayout()
        box.setSpacing(5)
        cap = QLabel(caption)
        cap.setObjectName("sub")
        cb = QComboBox()
        cb.addItems(list(items) or ["（无）"])
        theme.style_combo_popup(cb)          # 弹层边框交给容器，否则会多一层直角框
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
        tbl.verticalHeader().setDefaultSectionSize(40)
        return tbl

    # ---------------------------------------------------------------- 交互
    def _on_download(self) -> None:
        """用当前条件已完成的报告生成下载计划。"""
        if not self.btn_download.isEnabled() or self._report is None:
            return
        from modcheck.gui.download_dialog import DownloadDialog

        DownloadDialog(self._service, self._report, self).exec()

    def _on_export(self) -> None:
        if self._report is None or self._worker is not None:
            return
        path = choose_json_output(self, "导出 JSON 报告", self._service.export_default_name())
        if not path:
            return                                    # 用户取消：什么都不做，不报错
        try:
            self._service.export_to(path)
            self.lb_status.setText("已导出：" + path)
        except ConfigError as exc:
            show_warning(self, "导出失败", exc.message)
        except Exception as exc:                      # 磁盘满/无权限：要让用户看见
            show_warning(self, "导出失败",
                         "报告没有写出去。请换一个位置，或确认目标文件没有被其它程序打开。",
                         detail=describe(exc))

    def _profile_name(self) -> str:
        return self.cb_profile.currentData() or ""

    def _on_mc_activated(self, index: int) -> None:
        """选中「自定义…」时弹窗输入版本号，并按**官方全量清单**校验。

        校验用全量、显示只用前 9 个：这样既能保持下拉简洁，
        又能填 1.21.4 这类较早的版本（以前下拉只有 10 个且不可编辑，根本填不进去）。
        """
        if self.cb_mc.itemText(index) != CUSTOM_MC:
            self._selected_mc = self._mc_name()
            self._on_target_changed()
            return
        self.cb_mc.setCurrentIndex(max(0, self.cb_mc.findText(self._selected_mc)))
        text, ok = QInputDialog.getText(
            self, "自定义游戏版本",
            "请输入官方正式版版本号（例如 1.21.4）：",
            text=self._selected_mc)
        value = (text or "").strip()
        if not ok or not value:
            return
        try:
            validate_target_version(value, self._known_mc)
        except ConfigError as exc:
            QMessageBox.warning(self, "无法使用这个版本", exc.message)
            return
        # 填进下拉并选中它（放在最前面，下次还能直接选到）
        if value not in [self.cb_mc.itemText(i) for i in range(self.cb_mc.count())]:
            self.cb_mc.insertItem(0, value)
        self.cb_mc.setCurrentIndex(self.cb_mc.findText(value))
        self._selected_mc = value
        self._on_target_changed()

    def _mc_name(self) -> str:
        """目标版本：**剥掉可能的中文后缀**，并去掉空格。

        下拉里某些条目带「（最新正式版）」这类注解，直接拿去当版本号会查不到。
        """
        value = self.cb_mc.currentText()
        return "" if value == CUSTOM_MC or value.startswith("（") else value

    def _on_start(self, *, refresh: bool = False) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.lb_progress.show_message("正在取消……")
            return
        profile = self._profile_name()
        mc = self._mc_name()
        if not profile or not mc:
            return
        self._discard_result()
        self._set_check_inputs_enabled(False)
        self._worker = CheckWorker(self._service, profile, mc,
                                   self.cb_loader.currentText(), self, refresh=refresh)
        self._worker.progressed.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_thread_finished)
        self._worker.finished.connect(self._worker.deleteLater)
        self.bar.setRange(0, 0)                 # 未知总数时显示忙碌动画
        self.btn_go.setText("取消")
        self.lb_progress.show_message("正在准备联网重查……" if refresh else "正在准备……")
        self._worker.start()

    def _on_progress(self, done: int, total: int, name: str) -> None:
        if self.bar.maximum() != total:
            self.bar.setRange(0, total)
        self.bar.setValue(done)
        self.lb_progress.show_message(f"正在检查 {done}/{total}：{name}")

    def _on_done(self, rows: list[Row]) -> None:
        self._report = getattr(self._service, "last_report", None)
        self._rows = list(rows)
        self._render()

    def _on_failed(self, message: str) -> None:
        self.lb_progress.show_message("检查失败：" + message)

    def _on_thread_finished(self) -> None:
        self._worker = None
        if self._close_pending:
            if self._versions_worker is None:
                self.close()
            return
        self.btn_go.setText("开始检查")
        self._set_check_inputs_enabled(True)
        self._update_check_button()
        self._update_report_buttons()
        self.bar.setRange(0, 1)
        self.bar.setValue(1 if self._rows else 0)

    def _set_check_inputs_enabled(self, enabled: bool) -> None:
        self.cb_profile.setEnabled(enabled and bool(self._profile_name()))
        self.cb_mc.setEnabled(enabled)
        self.cb_loader.setEnabled(enabled)
        self.menuBar().setEnabled(enabled)

    # ---------------------------------------------------------------- 渲染
    def _render(self) -> None:
        groups: dict[str, list[Row]] = {}
        for r in self._rows:
            groups.setdefault(r.status, []).append(r)
        order = ["blocked", "prerelease", "degraded", "unknown", "ready", "ignored"]
        report = self._report

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
        if report is not None:
            prefix = "检查已取消" if report.interrupted else "检查完成"
            summary = (f"{prefix} · {report.profile_name} · {report.mc_version} · "
                       f"{report.loader.display_name} · {len(self._rows)} 个模组")
        else:
            summary = f"检查完成，共 {len(self._rows)} 个模组"
        self.lb_progress.show_summary(summary, report.warnings if report is not None else ())

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
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            parts = [part for part in (r.reason, "可用版本 " + r.available if r.available else "",
                                      "模组 ID " + "、".join(r.mod_ids) if r.mod_ids else "") if part]
            details = "\n".join(parts)
            for column, text in ((0, r.name), (2, r.version), (3, r.date)):
                item = QTableWidgetItem(text)
                item.setToolTip(details)
                self.table.setItem(i, column, item)
            self.table.setCellWidget(i, 1, theme.status_chip(r.status))


__all__ = ["MainWindow", "CheckWorker", "CheckService", "Row"]
