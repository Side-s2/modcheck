"""modcheck —— Minecraft 服务端模组版本兼容性检查工具。

入口调用 flows，核心判定通过接口使用数据源。PyQt6 只用于图形界面。
"""
from __future__ import annotations

__version__: str = "0.1.1"
APP_NAME: str = "modcheck"
APP_TITLE: str = "Minecraft 模组版本检查工具"

__all__ = ["__version__", "APP_NAME", "APP_TITLE"]
