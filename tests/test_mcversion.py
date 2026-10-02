"""T-05 MC 版本号测试：年份制与 1.x 制都要正确。"""
from __future__ import annotations

import pytest

from modcheck.core.mcversion import (compare, is_release_like, is_snapshot_like, max_release,
                                     sort_releases, validate_target_version, version_key)
from modcheck.errors import ConfigError


def test_release_and_snapshot_detection() -> None:
    """年份制与 1.x 制都算正式版；快照与乱填都不算。"""
    for value in ("26.3", "26.1.2", "1.21.4", "1.7.10"):
        assert is_release_like(value) is True
    for value in ("26.4-snapshot-2", "24w14a", "1.21-pre1", "abc", "26", "26.3.1.1"):
        assert is_release_like(value) is False
    for value in ("26.4-snapshot-2", "24w14a", "1.21-pre1", "1.21-rc1"):
        assert is_snapshot_like(value) is True
    assert is_snapshot_like("26.3") is False


def test_version_key_and_compare() -> None:
    """版本号比较必须按数字，不能按字符串。"""
    assert version_key("26.1.2") == (26, 1, 2)
    assert version_key("26.3") == (26, 3, 0)
    assert version_key("abc") == (-1, -1, -1)
    assert compare("1.21.11", "1.21.4") == 1
    assert compare("26.1", "1.21.11") == 1
    assert compare("26.1", "26.1.0") == 0


def test_max_release_prefers_year_based() -> None:
    """年份制大于 1.x 制；快照不参与。"""
    assert max_release(["1.21.4", "26.1", "1.21.11", "26.3-snapshot-2"]) == "26.1"
    assert max_release(["1.21.4", "1.21.11"]) == "1.21.11"
    assert max_release(["abc", "24w14a"]) is None
    assert max_release([]) is None


def test_sort_releases_desc() -> None:
    """按从新到旧排序并去重。"""
    assert sort_releases(["1.21.4", "26.1", "1.21.11", "26.1"]) == ["26.1", "1.21.11", "1.21.4"]


def test_validate_ok_when_known_empty() -> None:
    """官方清单没取到时跳过存在性检查。"""
    validate_target_version("26.3", None)
    validate_target_version("26.3", set())
    validate_target_version("26.3", {"26.3", "26.2"})


def test_validate_errors() -> None:
    """三类错误文案必须与 PRD E07/E08/E09 一致。"""
    with pytest.raises(ConfigError) as exc:
        validate_target_version("abc", {"26.3"})
    assert "无法识别的游戏版本" in str(exc.value)
    assert "26.3 或 1.21.4" in str(exc.value)

    with pytest.raises(ConfigError) as exc2:
        validate_target_version("26.4-snapshot-2", {"26.3"})
    assert "是快照版本" in str(exc2.value)

    with pytest.raises(ConfigError) as exc3:
        validate_target_version("26.9", {"26.3", "26.2", "26.1.2"})
    assert "官方版本列表中不存在「26.9」" in str(exc3.value)
    assert "26.3、26.2、26.1.2" in str(exc3.value)
