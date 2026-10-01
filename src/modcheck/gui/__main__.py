"""modcheck GUI 入口。

用法：
    python -m modcheck.gui          （开发时）
    modcheck-gui.exe                （打包产物）

与 CLI 的关系：**同一份 core 与 flows，只是换了个前端**。
配置文件与清单目录与 CLI 共用，所以两个界面的数据天然一致。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from modcheck.gui.backend import CliBackend
from modcheck.gui.main_window import MainWindow
from modcheck.gui.theme import QSS


def main(argv: list[str] | None = None) -> int:
    """启动界面；返回进程退出码。"""
    args = list(sys.argv[1:] if argv is None else argv)
    config_dir = None
    if "--config-dir" in args:
        index = args.index("--config-dir")
        if index + 1 < len(args):
            config_dir = Path(args[index + 1])

    app = QApplication(sys.argv)
    app.setApplicationName("modcheck")
    app.setApplicationDisplayName("Minecraft 模组兼容性检查")
    # Fusion 让样式在各版本 Windows 上一致 —— 原生样式会把我们设的圆角/内边距吃掉
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)

    try:
        backend = CliBackend(config_dir=config_dir)
    except Exception as exc:                      # 配置目录不可用等：给出可读提示而不是崩
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "启动失败", f"无法初始化：{exc}")
        return 1

    window = MainWindow(backend)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
