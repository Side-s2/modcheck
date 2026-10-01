"""pytest 公共夹具：fixture 读取 + 假数据源。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(Path(__file__).parent))


def load_fixture(name: str) -> Any:
    """读取 tests/fixtures 下的 JSON 文本夹具。"""
    path = FIXTURES / name
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture()
def fixtures_dir() -> Path:
    """fixture 目录。"""
    return FIXTURES
