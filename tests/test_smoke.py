"""M0 冒烟测试：包可以 import、--version 输出正确。"""
from __future__ import annotations

import modcheck


def test_version() -> None:
    """版本号与包名符合 T-01 契约。"""
    assert modcheck.__version__ == "0.1.0"
    assert modcheck.APP_NAME == "modcheck"


def test_main_is_importable() -> None:
    """cli.main 必须能被 import（--version / --help 依赖它）。"""
    from modcheck.cli.main import build_parser, main

    assert callable(main)
    assert build_parser() is not None
