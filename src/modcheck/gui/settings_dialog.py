"""设置对话框（GUI 二期）。

**校验规则全部来自 core/settings_ops.py**（代理格式、并发范围、null 语义…），
界面只负责取值与显示错误 —— 这样 CLI 菜单 [4] 与 GUI 不可能出现"一边能存一边不能存"。
"""
from __future__ import annotations

from PyQt6.QtWidgets import (QAbstractSpinBox, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
                             QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                             QSpinBox, QVBoxLayout, QWidget)

from modcheck.gui import theme
from modcheck.gui.dialogs import describe, show_warning


class SettingsDialog(QDialog):
    """编辑 GUI 当前支持的设置。"""

    def __init__(self, backend, parent: QWidget | None = None, *, known_versions=()) -> None:
        super().__init__(parent)
        self._backend = backend
        self._ops = backend.settings_ops()
        self._settings = backend.load_settings()
        self._known_versions = known_versions
        self.setWindowTitle("设置")
        self.resize(620, 460)
        self._build()
        self._load()

    # ---------------------------------------------------------------- 构建
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(12)

        title = QLabel("设置")
        title.setObjectName("title")
        outer.addWidget(title)
        hint = QLabel("代理、并发数和缓存设置将在保存后用于后续操作。")
        hint.setObjectName("sub")
        outer.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(10)

        self.ed_mc = QLineEdit()
        self.ed_mc.setPlaceholderText("例如 26.3（留空表示每次询问）")
        form.addRow("默认游戏版本", self.ed_mc)

        self.cb_loader = QComboBox()
        self.cb_loader.addItems(["Fabric", "NeoForge", "Forge"])
        theme.style_combo_popup(self.cb_loader)
        form.addRow("默认加载器", self.cb_loader)

        self.cb_theme = QComboBox()
        for label, value in (("跟随系统", "auto"), ("浅色", "light"), ("深色", "dark")):
            self.cb_theme.addItem(label, value)
        theme.style_combo_popup(self.cb_theme)
        form.addRow("外观", self.cb_theme)

        self.ed_proxy = QLineEdit()
        self.ed_proxy.setPlaceholderText("HTTP 代理，例如 http://127.0.0.1:7890")
        form.addRow("代理", self.ed_proxy)

        self.sp_jobs = QSpinBox()
        self.sp_jobs.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.sp_jobs.setRange(1, 8)
        form.addRow("并发数", self.sp_jobs)

        self.sp_ttl = QDoubleSpinBox()
        self.sp_ttl.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.sp_ttl.setRange(self._ops.TTL_LOW, self._ops.TTL_HIGH)
        self.sp_ttl.setDecimals(1)
        self.sp_ttl.setSuffix(" 小时")
        form.addRow("缓存有效期（API）", self.sp_ttl)
        self.ck_cache = QCheckBox("优先使用有效缓存进行兼容性检查")
        form.addRow("检查来源", self.ck_cache)

        outer.addLayout(form)
        outer.addStretch(1)

        foot = QHBoxLayout()
        reset = QPushButton("重置为默认")
        reset.clicked.connect(self._on_reset)
        foot.addWidget(reset)
        foot.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        foot.addWidget(cancel)
        save = QPushButton("保存")
        save.setObjectName("primary")
        save.clicked.connect(self._on_save)
        foot.addWidget(save)
        outer.addLayout(foot)

    # ---------------------------------------------------------------- 读写
    def _load(self) -> None:
        s = self._settings
        self.ed_mc.setText(s.default_mc_version or "")
        self.cb_loader.setCurrentText(s.default_loader.display_name)
        self.cb_theme.setCurrentIndex(self.cb_theme.findData(s.theme))
        self.ed_proxy.setText(s.proxy or "")
        self.sp_jobs.setValue(int(s.concurrency))
        ttl = float(s.cache_ttl_hours.get("api", 6))
        self.sp_ttl.setRange(min(ttl, self._ops.TTL_LOW), max(ttl, self._ops.TTL_HIGH))
        self.sp_ttl.setValue(ttl)
        self._displayed_ttl = self.sp_ttl.value()
        self.ck_cache.setChecked(s.check_cache)

    def _collect(self):
        """把界面上的值交给 core 的 setter 逐个校验；任何一个非法就报错并中止。"""
        ops, s = self._ops, self._ops.clone(self._settings)
        s = ops.set_default_mc(s, self.ed_mc.text().strip() or None, known=self._known_versions)
        # ⚠️ set_default_loader 收的是**字符串**（value: str | None），不是 Loader 枚举 ——
        # 传枚举会被 str() 成 "Loader.FABRIC" 然后报「暂不支持加载器 Loader.FABRIC」。
        # CLI 那边传的是 chosen.value，这里保持一致。
        s = ops.set_default_loader(s, self.cb_loader.currentText())
        s = ops.set_proxy(s, self.ed_proxy.text().strip() or None)
        s = ops.set_concurrency(s, self.sp_jobs.value())
        if self.sp_ttl.value() != self._displayed_ttl:
            s = ops.set_cache_ttl(s, "api", self.sp_ttl.value())
        s.theme = self.cb_theme.currentData()
        s.check_cache = self.ck_cache.isChecked()
        return s

    # ---------------------------------------------------------------- 动作
    def _on_save(self) -> None:
        try:
            settings = self._collect()
        except Exception as exc:                 # 校验失败：core 给的就是给人看的句子
            show_warning(self, "这项填得不对", str(exc))
            return
        try:
            self._backend.save_settings(settings)
        except Exception as exc:
            show_warning(self, "保存失败",
                         "设置没有写入。请确认配置目录可写（磁盘空间、文件占用）。",
                         detail=describe(exc))
            return
        self.accept()

    def _on_reset(self) -> None:
        if QMessageBox.question(self, "重置为默认",
                                "将此窗口中的设置恢复为默认值？"
                                ) != QMessageBox.StandardButton.Yes:
            return
        defaults = self._ops.reset_settings()
        self._settings = self._ops.clone(self._settings)
        self._settings.default_mc_version = defaults.default_mc_version
        self._settings.default_loader = defaults.default_loader
        self._settings.proxy = defaults.proxy
        self._settings.theme = defaults.theme
        self._settings.check_cache = defaults.check_cache
        self._settings.concurrency = defaults.concurrency
        self._settings.cache_ttl_hours["api"] = defaults.cache_ttl_hours["api"]
        self._load()


__all__ = ["SettingsDialog"]
