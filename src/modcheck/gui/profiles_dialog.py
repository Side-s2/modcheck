"""清单管理对话框（GUI 二期）。

操作规则**全部来自 core/profile_ops.py**（全标识定位、忽略切换、指定项目…），
界面只负责"选哪个、填什么、确认与否"。这样 CLI 菜单 [3] 与 GUI 是同一套行为。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QInputDialog,
                             QLabel, QListWidget, QMessageBox, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from modcheck.gui import theme


class ProfilesDialog(QDialog):
    """左边清单列表，右边该清单的模组；下方是各种操作。"""

    def __init__(self, backend, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._backend = backend
        self._profile = None
        self.setWindowTitle("管理模组清单")
        self.resize(980, 620)
        self._build()
        self._reload_profiles()

    # ---------------------------------------------------------------- 构建
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        title = QLabel("管理模组清单")
        title.setObjectName("title")
        outer.addWidget(title)
        hint = QLabel("左侧选清单，右侧操作其中的模组。所有改动立即写盘。")
        hint.setObjectName("sub")
        outer.addWidget(hint)

        body = QHBoxLayout()
        body.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(6)
        left.addWidget(QLabel("模组清单"))
        self.list = QListWidget()
        self.list.currentTextChanged.connect(self._on_pick_profile)
        left.addWidget(self.list, 1)
        for text, slot in (("新建空清单", self._on_new), ("重命名清单", self._on_rename),
                           ("删除清单", self._on_delete)):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            left.addWidget(btn)
        body.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(6)
        self.lb_profile = QLabel("（未选择清单）")
        self.lb_profile.setStyleSheet("font-weight:600;")
        right.addWidget(self.lb_profile)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["模组", "平台标识", "状态"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 200)
        self.table.setColumnWidth(2, 110)
        # 统一行高，而不是逐行 setRowHeight：
        # 实测"先 setCellWidget 再 setRowHeight"会让**第一行**的控件停在 (0,0) 不重新定位，
        # 看起来像是叠在"模组"列上。用默认行高就没有这个重排时机问题。
        self.table.verticalHeader().setDefaultSectionSize(34)
        right.addWidget(self.table, 1)

        ops = QHBoxLayout()
        for text, slot in (("忽略 / 取消忽略", self._on_toggle_ignore),
                           ("指定平台项目", self._on_set_source),
                           ("删除模组", self._on_remove_mod)):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            ops.addWidget(btn)
        ops.addStretch(1)
        right.addLayout(ops)
        body.addLayout(right, 3)
        outer.addLayout(body, 1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        close = QPushButton("关闭")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        foot.addWidget(close)
        outer.addLayout(foot)

    # ---------------------------------------------------------------- 数据
    def _reload_profiles(self, keep: str | None = None) -> None:
        want = keep or (self.list.currentItem().text() if self.list.currentItem() else None)
        self.list.blockSignals(True)
        self.list.clear()
        for name, count in self._backend.profiles():
            self.list.addItem(f"{name}（{count} 个模组）")
        self.list.blockSignals(False)
        if self.list.count():
            row = 0
            if want:
                for i in range(self.list.count()):
                    if self.list.item(i).text().startswith(want):
                        row = i
                        break
            self.list.setCurrentRow(row)
            self._on_pick_profile(self.list.item(row).text())

    def _name_of(self, label: str) -> str:
        return label.split("（")[0]

    def _current_name(self) -> str | None:
        item = self.list.currentItem()
        return self._name_of(item.text()) if item else None

    def _selected_mod(self) -> str | None:
        row = self.table.currentRow()
        if row < 0 or self._profile is None or row >= len(self._profile.mods):
            return None
        entry = self._profile.mods[row]
        return entry.file_name or entry.key

    def _on_pick_profile(self, label: str) -> None:
        if not label:
            return
        name = self._name_of(label)
        try:
            self._profile = self._backend.load_profile(name)
        except Exception as exc:
            QMessageBox.warning(self, "读不到清单", f"{type(exc).__name__}: {exc}")
            return
        self.lb_profile.setText(f"{name}　·　共 {len(self._profile.mods)} 个模组")
        self._fill_table()

    def _fill_table(self) -> None:
        mods = self._profile.mods if self._profile else []
        # ⚠️ 必须先清空再填。_reload_profiles 里的 setCurrentRow 会**再触发一次**
        # _on_pick_profile，于是本函数跑两次；第一次创建的 cell widget 不会被
        # setRowCount 回收，会变成游离控件停在 (0,0) —— 实测它在真实窗口里
        # 就叠在「模组」列上（不是截图假象，show() 之后依然存在）。
        self.table.setRowCount(0)
        self.table.setRowCount(len(mods))
        for i, entry in enumerate(mods):
            self.table.setItem(i, 0, QTableWidgetItem(entry.file_name or entry.key))
            self.table.setItem(i, 1, QTableWidgetItem((entry.sources or {}).get("modrinth", "")
                                                      or entry.mod_id or ""))
            ignored = bool(getattr(entry, "ignored", False))
            chip = theme.status_chip("ignored" if ignored else "ready")
            chip.setText("· 已忽略" if ignored else "· 参与检查")
            self.table.setCellWidget(i, 2, chip)

    # ---------------------------------------------------------------- 操作
    def _commit(self, result) -> None:
        """core 返回 OpResult：成功了才写盘，失败只提示。"""
        if not getattr(result, "ok", True):
            QMessageBox.information(self, "没有改动", getattr(result, "message", "操作未生效"))
            return
        try:
            self._backend.save_profile(self._profile)
        except Exception as exc:
            QMessageBox.warning(self, "写盘失败", f"{type(exc).__name__}: {exc}\n本次改动没有保存。")
            return
        self._reload_profiles(self._profile.name)

    def _on_new(self) -> None:
        name, ok = QInputDialog.getText(self, "新建空清单", "清单名：")
        if not ok or not name.strip():
            return
        try:
            self._backend.create_profile(name.strip())
        except Exception as exc:
            QMessageBox.warning(self, "建不了", str(exc))
            return
        self._reload_profiles(name.strip())

    def _on_rename(self) -> None:
        old = self._current_name()
        if not old:
            return
        name, ok = QInputDialog.getText(self, "重命名清单", "新名字：", text=old)
        if not ok or not name.strip() or name.strip() == old:
            return
        try:
            self._backend.rename_profile_file(old, name.strip())
        except Exception as exc:
            QMessageBox.warning(self, "改不了", str(exc))
            return
        self._reload_profiles(name.strip())

    def _on_delete(self) -> None:
        name = self._current_name()
        if not name:
            return
        # 唯一不可撤销的操作：要求**完整输入清单名**（比 y/N 强，防手滑）
        typed, ok = QInputDialog.getText(
            self, "删除清单",
            f"删除后无法恢复。请输入清单名「{name}」以确认：")
        if not ok or typed.strip() != name:
            return
        try:
            self._backend.delete_profile_file(name)
        except Exception as exc:
            QMessageBox.warning(self, "删不掉", str(exc))
            return
        self._profile = None
        self._reload_profiles()

    def _on_toggle_ignore(self) -> None:
        selector = self._selected_mod()
        if not selector or self._profile is None:
            return
        entry = self._profile.mods[self.table.currentRow()]
        self._commit(self._backend.set_ignored(self._profile, selector,
                                               not bool(getattr(entry, "ignored", False))))

    def _on_set_source(self) -> None:
        selector = self._selected_mod()
        if not selector or self._profile is None:
            return
        raw, ok = QInputDialog.getText(
            self, "指定平台项目",
            "填 Modrinth 的项目链接或 slug（例如 https://modrinth.com/mod/carpet 或 carpet）：")
        if not ok or not raw.strip():
            return
        from modcheck.core.profile_ops import parse_project_selector

        slug = parse_project_selector(raw.strip())
        if not slug:
            QMessageBox.warning(self, "看不懂这个输入", "请填项目链接或 slug。")
            return
        self._commit(self._backend.set_source(self._profile, selector,
                                              provider="modrinth", slug=slug))

    def _on_remove_mod(self) -> None:
        selector = self._selected_mod()
        if not selector or self._profile is None:
            return
        if QMessageBox.question(self, "删除模组",
                                f"从清单里移除「{selector}」？\n"
                                "（只影响清单，不会动你的 mods 文件夹）"
                                ) != QMessageBox.StandardButton.Yes:
            return
        self._commit(self._backend.remove_mods(self._profile, [selector]))


__all__ = ["ProfilesDialog"]
