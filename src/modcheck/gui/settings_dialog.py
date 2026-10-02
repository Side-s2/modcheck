"""设置对话框（GUI 二期）。

**校验规则全部来自 core/settings_ops.py**（代理格式、并发范围、null 语义…），
界面只负责取值与显示错误 —— 这样 CLI 菜单 [4] 与 GUI 不可能出现"一边能存一边不能存"。
"""
from __future__ import annotations

from PyQt6.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from modcheck.gui import theme
from modcheck.gui.dialogs import describe, show_warning


class SettingsDialog(QDialog):
    """七个设置项 + 重置为默认。"""

    def __init__(self, backend, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._backend = backend
        self._ops = backend.settings_ops()
        self._settings = backend.load_settings()
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
        hint = QLabel("这些是全局默认值，CLI 与 GUI 共用同一份配置文件。")
        hint.setObjectName("sub")
        outer.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(10)

        self.ed_mc = QLineEdit()
        self.ed_mc.setPlaceholderText("例如 26.3（留空表示每次询问）")
        form.addRow("默认游戏版本", self.ed_mc)

        self.cb_loader = QComboBox()
        self.cb_loader.addItems(["（每次询问）", "Fabric", "NeoForge", "Forge"])
        form.addRow("默认加载器", self.cb_loader)

        self.ed_proxy = QLineEdit()
        self.ed_proxy.setPlaceholderText("例如 http://127.0.0.1:7890；填 null / none / - 表示清除")
        form.addRow("代理", self.ed_proxy)

        self.cb_color = QComboBox()
        self.cb_color.addItems(["auto", "always", "never"])
        form.addRow("彩色输出", self.cb_color)

        self.sp_jobs = QSpinBox()
        self.sp_jobs.setRange(1, 8)
        form.addRow("并发数", self.sp_jobs)

        self.sp_ttl = QSpinBox()
        self.sp_ttl.setRange(1, 720)
        self.sp_ttl.setSuffix(" 小时")
        form.addRow("缓存有效期（API）", self.sp_ttl)

        self.ed_cf = QLineEdit()
        self.ed_cf.setPlaceholderText("留空表示不启用 CurseForge")
        form.addRow("CurseForge API Key", self.ed_cf)

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
    def _cf_key(self) -> str | None:
        """CurseForge 的 Key 藏在 providers 字典里，不是独立字段。"""
        return (self._settings.providers.get("curseforge") or {}).get("api_key")

    def _load(self) -> None:
        s = self._settings
        self.ed_mc.setText(s.default_mc_version or "")
        self.cb_loader.setCurrentText(s.default_loader.display_name if s.default_loader else "（每次询问）")
        self.ed_proxy.setText(s.proxy or "")
        self.cb_color.setCurrentText(s.color or "auto")
        self.sp_jobs.setValue(int(s.concurrency))
        self.sp_ttl.setValue(int(s.cache_ttl_hours.get("api", 6)))
        key = self._cf_key()
        self.ed_cf.setText(self._ops.mask_secret(key) if key else "")

    def _collect(self):
        """把界面上的值交给 core 的 setter 逐个校验；任何一个非法就报错并中止。"""
        ops, s = self._ops, self._ops.clone(self._settings)
        # ⚠️ known 是**必填**关键字参数（官方正式版清单）：漏传会直接 TypeError，
        # 表现就是用户改默认版本时弹「参数缺失」。取不到版本清单时传空集合，
        # set_default_mc 会跳过「是否存在」检查（离线也不该拦住用户改设置）。
        try:
            known = tuple(self._backend.versions())
        except Exception:
            known = ()
        s = ops.set_default_mc(s, self.ed_mc.text().strip() or None, known=known)
        # ⚠️ set_default_loader 收的是**字符串**（value: str | None），不是 Loader 枚举 ——
        # 传枚举会被 str() 成 "Loader.FABRIC" 然后报「暂不支持加载器 Loader.FABRIC」。
        # CLI 那边传的是 chosen.value，这里保持一致。
        name = self.cb_loader.currentText()
        s = ops.set_default_loader(s, None if name.startswith("（") else name.lower())
        s = ops.set_proxy(s, self.ed_proxy.text().strip() or None)
        s = ops.set_color(s, self.cb_color.currentText())
        s = ops.set_concurrency(s, self.sp_jobs.value())
        s = ops.set_cache_ttl(s, "api", float(self.sp_ttl.value()))
        key = self.ed_cf.text().strip()
        # 掩码值原样写回，避免把 **** 存进去
        # 掩码值原样写回，避免把 ****xxxx 当成新 key 存进配置里。
        # ⚠️ key 存在 providers["curseforge"]["api_key"]，**没有** Settings.curseforge_key 这个属性
        current = self._cf_key()
        masked = ops.mask_secret(current) if current else ""
        if key != masked:
            s = ops.set_curseforge_key(s, key or None)
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
                                "把所有设置恢复成默认值？\n"
                                "（会覆盖默认版本、加载器、代理、并发、缓存有效期、API Key）"
                                ) != QMessageBox.StandardButton.Yes:
            return
        self._settings = self._ops.reset_settings()
        self._load()


__all__ = ["SettingsDialog"]
