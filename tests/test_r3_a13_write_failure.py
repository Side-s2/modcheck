"""R3-A13：写盘失败的统一处理（7 类操作 + 存储层领域异常）。"""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from modcheck.core.models import ModEntry, Settings
from modcheck.errors import ConfigError, ProfileError
from modcheck.storage.profiles import (load_profile, new_profile, profile_path, save_profile,
                                       delete_profile)
from modcheck.storage.settings import load_settings, save_settings

WINDOWS_ONLY = pytest.mark.skipif(os.name != "nt", reason="只读文件的语义在 Windows 上才可靠")


def write_profile(tmp_path: Path, name: str, count: int = 2) -> Path:
    """写一份清单文件。"""
    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)
    profile = new_profile(name)
    profile.mods = [ModEntry(key="m" + str(i), display_name="Mod" + str(i), mod_id="m" + str(i))
                    for i in range(count)]
    path = profile_path(tmp_path / "profiles", name)
    save_profile(profile, path)
    return path


def read_only(path: Path) -> None:
    """把文件设成只读（Windows 上 os.replace 会因此失败）。"""
    os.chmod(path, stat.S_IREAD)


def writable(path: Path) -> None:
    """恢复可写（清理用，必须在 finally 里调）。"""
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


# ---------------------------------------------------------------- 存储层：领域异常
def test_save_profile_raises_domain_error(tmp_path: Path) -> None:
    """写盘失败必须抛 ProfileError（不许把 OSError 甩给用户）。"""
    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)
    blocking = tmp_path / "profiles" / "blocked"
    blocking.write_text("i am a file", encoding="utf-8")     # 同名文件挡住目录创建
    with pytest.raises(ProfileError) as exc:
        save_profile(new_profile("x"), blocking / "x.json")
    assert "无法写入" in str(exc.value)


def test_delete_profile_raises_domain_error(tmp_path: Path) -> None:
    """删不掉必须是 ProfileError（不是 OSError）。"""
    target = tmp_path / "gone.json"
    target.mkdir()                                          # 目录删不掉（非空）
    (target / "child").write_text("x", encoding="utf-8")
    with pytest.raises(ProfileError):
        delete_profile(target)


def test_save_settings_raises_domain_error(tmp_path: Path) -> None:
    """设置写盘失败必须是 ConfigError。"""
    blocking = tmp_path / "blocked"
    blocking.write_text("x", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        save_settings(blocking / "settings.json", Settings())
    assert "无法写入" in str(exc.value)


def test_failed_save_leaves_no_tmp(tmp_path: Path) -> None:
    """失败后不许留下 .tmp 半成品。"""
    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)
    blocking = tmp_path / "profiles" / "blocked"
    blocking.write_text("x", encoding="utf-8")
    with pytest.raises(ProfileError):
        save_profile(new_profile("x"), blocking / "x.json")
    assert list(tmp_path.rglob("*.tmp")) == []
