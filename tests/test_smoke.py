"""验证版本及 GUI 入口。"""
from __future__ import annotations

import modcheck


def test_version() -> None:
    """版本号与包名符合 T-01 契约。"""
    assert modcheck.__version__ == "0.1.1"
    assert modcheck.APP_NAME == "modcheck"


def test_main_is_importable() -> None:
    import pytest

    pytest.importorskip("PyQt6")
    from modcheck.__main__ import main
    from modcheck.gui.__main__ import main as gui_main

    assert main is gui_main
