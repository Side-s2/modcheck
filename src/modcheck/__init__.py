"""modcheck —— Minecraft 服务端模组版本兼容性检查工具。

本包只依赖 Python 3.11 标准库；分层依赖方向为：
``cli -> core <- providers``、``cli -> storage``、``core -> models``。
core 层绝对不 import 具体 Provider 实现，只接收注入的接口对象。
"""
from __future__ import annotations

__version__: str = "0.1.0"
APP_NAME: str = "modcheck"
APP_TITLE: str = "Minecraft 模组版本检查工具"

__all__ = ["__version__", "APP_NAME", "APP_TITLE"]
