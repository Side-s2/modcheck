"""清单管理对话框（GUI 二期）。

操作规则**全部来自 core/profile_ops.py**（全标识定位、忽略切换、指定项目…），
界面只负责"选哪个、填什么、确认与否"。这样 CLI 菜单 [3] 与 GUI 是同一套行为。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
                             QInputDialog, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from modcheck.core.models import MatchStatus
from modcheck.core.profile_ops import parse_project_selector
from modcheck.errors import ConfigError, ModcheckError, UserCancelled
from modcheck.flows.export import modlist_filename
from modcheck.gui import theme
from modcheck.gui.dialogs import choose_json_output, describe, show_info, show_warning


class ProjectVerification(QThread):
    verified = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, backend, slug: str, parent: QWidget) -> None:
        super().__init__(parent)
        self._backend = backend
        self._slug = slug

    def run(self) -> None:
        try:
            project = self._backend.verify_project(self._slug, self.isInterruptionRequested)
        except UserCancelled:
            return
        except ModcheckError as exc:
            self.failed.emit(exc.message)
        except Exception as exc:
            self.failed.emit(describe(exc))
        else:
            self.verified.emit(project)


class ProfilesDialog(QDialog):
    """左边清单列表，右边该清单的模组；下方是各种操作。"""

    profiles_changed = pyqtSignal()

    def __init__(self, backend, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._backend = backend
        self._profile = None
        self._verification: ProjectVerification | None = None
        self._verification_target = None
        self._pending_close: int | None = None
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
        self.list.setObjectName("profileList")
        self.list.currentRowChanged.connect(self._on_pick_profile)
        left.addWidget(self.list, 1)
        self._profile_actions = []
        self._manage_buttons = []
        for text, slot in (("新建空清单", self._on_new), ("重命名清单", self._on_rename),
                           ("删除清单", self._on_delete), ("导出JSON清单", self._on_export),
                           ("从JSON导入清单", self._on_import)):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            left.addWidget(btn)
            self._manage_buttons.append(btn)
            if slot in (self._on_rename, self._on_export, self._on_delete):
                self._profile_actions.append(btn)
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
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
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
        self.table.verticalHeader().setDefaultSectionSize(40)
        right.addWidget(self.table, 1)

        ops = QHBoxLayout()
        self._mod_actions = []
        for text, slot in (("忽略 / 取消忽略", self._on_toggle_ignore),
                           ("指定平台项目", self._on_set_source),
                           ("删除模组", self._on_remove_mod)):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            ops.addWidget(btn)
            self._mod_actions.append(btn)
        self.table.itemSelectionChanged.connect(self._update_mod_actions)
        ops.addStretch(1)
        right.addLayout(ops)
        body.addLayout(right, 3)
        outer.addLayout(body, 1)

        foot = QHBoxLayout()
        self.lb_verification = QLabel()
        self.lb_verification.setObjectName("sub")
        foot.addWidget(self.lb_verification)
        foot.addStretch(1)
        close = QPushButton("关闭")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        foot.addWidget(close)
        outer.addLayout(foot)

    # ---------------------------------------------------------------- 数据
    def _reload_profiles(self, keep: str | None = None) -> None:
        want = keep or self._current_name()
        row = -1
        try:
            profiles = self._backend.profiles()
        except (OSError, ValueError) as exc:
            profiles = ()
            show_warning(self, "无法读取清单目录", describe(exc))
        self.list.blockSignals(True)
        self.list.clear()
        for index, (name, count) in enumerate(profiles):
            item = QListWidgetItem(f"{name}（{count} 个模组）")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list.addItem(item)
            if row == -1 or name == want:
                row = index
        self.list.setCurrentRow(row)
        self.list.blockSignals(False)
        self._on_pick_profile(row)

    def _current_name(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selected_mod(self) -> str | None:
        row = self.table.currentRow()
        if not self.table.selectedItems() or self._profile is None or not 0 <= row < len(self._profile.mods):
            return None
        # 核心接口接受从 1 开始的编号。直接使用选中行可避免同名文件选错条目。
        return str(row + 1)

    def _update_mod_actions(self) -> None:
        enabled = self._verification is None and self._selected_mod() is not None
        for button in self._mod_actions:
            button.setEnabled(enabled)

    def _on_pick_profile(self, row: int) -> None:
        self._profile = None
        self.table.setRowCount(0)
        self._update_mod_actions()
        for button in self._profile_actions:
            button.setEnabled(row >= 0)
        if row < 0:
            self.lb_profile.setText("暂无清单。可以新建或导入清单。")
            return
        name = self.list.item(row).data(Qt.ItemDataRole.UserRole)
        try:
            self._profile = self._backend.load_profile(name)
        except Exception as exc:
            self.lb_profile.setText(f"无法读取「{name}」")
            show_warning(self, "读不到清单",
                         "这个清单文件读不出来，可能已损坏或被其它程序占用。",
                         detail=describe(exc))
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
            name = QTableWidgetItem(entry.file_name or entry.key)
            if entry.detected.mod_ids:
                name.setToolTip("模组 ID\n" + "\n".join(entry.detected.mod_ids))
            self.table.setItem(i, 0, name)
            self.table.setItem(i, 1, QTableWidgetItem((entry.sources or {}).get("modrinth", "")
                                                      or entry.mod_id or ""))
            # ⚠️ 忽略态在 match_status 里，**ModEntry 没有 ignored 字段**。
            # 原先写的是 getattr(entry, "ignored", False) —— 恒为 False，
            # 于是状态列永远显示"参与检查"，而且 toggle 永远传 True：
            # **一旦点了忽略就再也取消不掉**（教程作者核对代码时发现的）。
            ignored = entry.match_status is MatchStatus.IGNORED
            chip = (theme.status_chip("ignored") if ignored
                    else theme.status_chip("ready", "参与检查"))
            self.table.setCellWidget(i, 2, chip)

    # ---------------------------------------------------------------- 操作
    def _commit(self, result) -> None:
        """core 返回 OpResult（changed / profile / message_key）—— 成功才写盘。

        ⚠️ 这里曾经有三个叠加的错误，导致**清单对话框点任何按钮都毫无反应且不报错**：
          1. 判断用了 result.ok —— OpResult **没有**这个字段，getattr 默认 True，等于从不拦截；
          2. 提示读了 result.message —— 也没有，永远显示兜底文案；
          3. **最要命的一条**：写盘写的是 self._profile（旧对象），
             而 profile_ops 是**不可变风格**：改完返回 result.profile，原对象纹丝不动。
             于是「删除模组 / 忽略 / 指定平台项目 / 重命名」全部静默失效。
        不可变风格本身是对的（好测试、好回滚），错在我把返回值丢了。
        """
        from modcheck.i18n import t

        if not getattr(result, "changed", False):
            key = getattr(result, "message_key", "") or ""
            try:
                msg = t(key, **getattr(result, "message_args", {})) if key else "没有需要改动的地方"
            except Exception:
                msg = "没有需要改动的地方"
            QMessageBox.information(self, "没有改动", msg)
            return
        try:
            self._backend.save_profile(result.profile)
        except Exception as exc:
            show_warning(self, "写盘失败", "本次改动**没有**保存。请确认配置目录可写。",
                         detail=describe(exc))
            return
        self._reload_profiles(result.profile.name)
        self.profiles_changed.emit()

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
        self.profiles_changed.emit()

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
        self.profiles_changed.emit()

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
        self.profiles_changed.emit()

    def _on_import(self) -> None:
        """导入别人导出的 JSON 清单（同名清单会自动合并）。"""
        path, _ = QFileDialog.getOpenFileName(self, "导入模组清单", "",
                                              "JSON 清单 (*.json)")
        if not path:
            return
        try:
            outcome = self._backend.import_modlist_file(path)
        except Exception as exc:
            # read_modlist 给的是**给人看的中文句子**（缺字段/类型不对等），直接显示
            show_warning(self, "导入失败",
                         str(exc) or "这个文件不是本工具导出的清单。",
                         detail=describe(exc))
            return
        name = getattr(outcome, "path", None)
        target = name.stem if name is not None else "清单"
        show_info(self, "已导入",
                  f"已导入 {getattr(outcome, 'imported', '?')} 个模组"
                  f"（合并后共 {len(getattr(outcome, 'merged', []) or [])} 个）"
                  + ("，并新建了清单。" if getattr(outcome, "created", False) else "。"))
        self._reload_profiles(target)
        self.profiles_changed.emit()

    def _on_export(self) -> None:
        """导出已保存的 JSON 清单。"""
        name = self._current_name()
        if not name:
            return
        path = choose_json_output(self, "导出JSON清单", modlist_filename(name))
        if not path:
            return
        try:
            self._backend.export_modlist_file(name, path)
        except ConfigError as exc:
            show_warning(self, "导出失败", exc.message)
            return
        except Exception as exc:
            show_warning(self, "导出失败",
                         "清单没有写出去。请换一个位置，或确认目标文件没有被其它程序打开。",
                         detail=describe(exc))
            return
        show_info(self, "已导出", f"清单「{name}」已导出为 JSON，可以再次导入。")

    def _on_toggle_ignore(self) -> None:
        selector = self._selected_mod()
        if not selector or self._profile is None:
            return
        entry = self._profile.mods[self.table.currentRow()]
        self._commit(self._backend.set_ignored(
            self._profile, selector,
            entry.match_status is not MatchStatus.IGNORED))

    def _on_set_source(self) -> None:
        selector = self._selected_mod()
        if not selector or self._profile is None or self._verification is not None:
            return
        raw, ok = QInputDialog.getText(
            self, "指定平台项目",
            "填 Modrinth 的项目链接或 slug（例如 https://modrinth.com/mod/carpet 或 carpet）：")
        if not ok or not raw.strip():
            return
        slug = parse_project_selector(raw.strip())
        if not slug:
            QMessageBox.warning(self, "看不懂这个输入", "请填项目链接或 slug。")
            return
        self._verification_target = (self._profile, selector)
        worker = ProjectVerification(self._backend, slug, self)
        self._verification = worker
        worker.verified.connect(self._on_project_verified)
        worker.failed.connect(self._on_verification_failed)
        worker.finished.connect(self._on_verification_finished)
        worker.finished.connect(worker.deleteLater)
        self.list.setEnabled(False)
        self.table.setEnabled(False)
        for button in self._manage_buttons:
            button.setEnabled(False)
        self._update_mod_actions()
        self.lb_verification.setText("正在联网验证 Modrinth 项目…")
        worker.start()

    def _on_project_verified(self, project) -> None:
        if self._pending_close is None:
            profile, selector = self._verification_target
            self._commit(self._backend.set_source(profile, selector, project=project))

    def _on_verification_failed(self, message: str) -> None:
        if self._pending_close is None:
            show_warning(self, "无法验证项目", message)

    def _on_verification_finished(self) -> None:
        self._verification = None
        self._verification_target = None
        if self._pending_close is not None:
            super().done(self._pending_close)
            return
        self.list.setEnabled(True)
        self.table.setEnabled(True)
        for button in self._manage_buttons:
            button.setEnabled(button not in self._profile_actions or self._current_name() is not None)
        self.lb_verification.clear()
        self._update_mod_actions()

    def done(self, status: int) -> None:
        if self._verification is not None:
            self._pending_close = status
            self._verification.requestInterruption()
            return
        super().done(status)

    def _on_remove_mod(self) -> None:
        selector = self._selected_mod()
        if not selector or self._profile is None:
            return
        entry = self._profile.mods[self.table.currentRow()]
        if QMessageBox.question(self, "删除模组",
                                f"从清单里移除「{entry.file_name or entry.best_name}」？\n"
                                "（只影响清单，不会动你的 mods 文件夹）"
                                ) != QMessageBox.StandardButton.Yes:
            return
        self._commit(self._backend.remove_mods(self._profile, [selector]))


__all__ = ["ProfilesDialog"]
