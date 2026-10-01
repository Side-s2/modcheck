# -*- coding: utf-8 -*-
"""测试骨架自检：验证 pytest 配置（src 布局、live 标记默认 deselect）可用。

本文件在程序员接管后可以删除或保留，不影响业务测试。
"""
import sys
import unicodedata

import pytest


def test_python_version_is_311_baseline():
    assert sys.version_info[:2] == (3, 11), f"应当用 3.11 运行测试，实际 {sys.version}"


def test_stdlib_targets_available():
    import json, tomllib, urllib.request, zipfile  # noqa: F401
    assert True


def test_cjk_width_helper_recipe():
    """验证中文宽度计算配方（console.py 会用到）。"""
    def width(s: str) -> int:
        return sum(2 if unicodedata.east_asian_width(c) in ("F", "W") else 1 for c in s)

    assert width("地毯") == 4
    assert width("Carpet") == 6
    # '[' + '地毯'(4) + ']' + ' ' + 'Carpet'(6)
    assert width("[地毯] Carpet") == 1 + 4 + 1 + 1 + 6


@pytest.mark.live
def test_live_is_deselected_by_default():
    raise AssertionError("这条测试默认必须被 deselect；若它被执行，说明 pyproject 的 -m 'not live' 没生效")
