"""R3-A13：写盘失败的统一处理（7 类操作 + 存储层领域异常）。"""
from __future__ import annotations

import io
import os
import stat
from pathlib import Path

import pytest
from fakes import FakeProvider

from modcheck.cli.context import AppContext
from modcheck.cli.prompts import Prompter
from modcheck.cli.screens_profiles import run_profiles_screen
from modcheck.cli.screens_settings import run_settings_screen
from modcheck.console import Console
from modcheck.core.models import Loader, ModEntry, Settings
from modcheck.errors import ConfigError, ProfileError
from modcheck.providers.registry import ProviderRegistry
from modcheck.storage.profiles import (load_profile, new_profile, profile_path, save_profile,
                                       delete_profile)
from modcheck.storage.settings import load_settings, save_settings

WINDOWS_ONLY = pytest.mark.skipif(os.name != "nt", reason="只读文件的语义在 Windows 上才可靠")


def feed(values: list[str]):
    """注入输入序列；用完后一律返回 q。"""
    queue = list(values)

    def _input(_prompt: str = "") -> str:
        return queue.pop(0) if queue else "q"

    return _input


def make_ctx(tmp_path: Path, values: list[str]) -> AppContext:
    """最小上下文（离线：版本屏走手动输入）。"""
    from fakes import FakeTransport
    from modcheck.errors import ProviderNetworkError
    from modcheck.providers.http import HttpConfig, HttpClient

    def handler(method: str, url: str, data, index: int):
        raise ProviderNetworkError("offline")

    console = Console(stream=io.StringIO(), color="never", width=100)
    client = HttpClient(HttpConfig(rate_limit_per_min=100000), transport=FakeTransport(handler))
    provider = FakeProvider(projects={"carpet": carpet_project()})
    # 指定平台项目只认 modrinth 数据源，所以假数据源要以 modrinth 的身份注册
    provider.name = "modrinth"
    provider.display_name = "Modrinth"
    return AppContext(settings=Settings(), config_dir=tmp_path, console=console,
                      registry=ProviderRegistry(providers=[provider]), cache=None,
                      client=client, interactive=True,
                      prompter=Prompter(input_fn=feed(values), out=console))


def out(ctx: AppContext) -> str:
    """取屏幕输出。"""
    return ctx.console.stream.getvalue()      # type: ignore[attr-defined]


def carpet_project():
    """一个能通过校验的假项目（指定平台项目用）。"""
    from modcheck.core.models import ProjectInfo

    return ProjectInfo(project_id="P1", slug="carpet", title="Carpet", description="",
                       project_type="mod", loaders=("fabric",), game_versions=("26.3",),
                       downloads=1, version_count=3)


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


# ---------------------------------------------------------------- 屏幕层：7 类操作
@WINDOWS_ONLY
def test_all_profile_operations_report_failure(tmp_path: Path) -> None:
    """只读清单文件：删除模组 / 指定 / 忽略 / 重命名 都打 ✗ 且文件字节不变。"""
    path = write_profile(tmp_path, "服务器A", 3)
    before = path.read_bytes()
    read_only(path)
    try:
        scenarios = [
            ("删除模组", ["1", "2", "1", "y", "q"]),
            ("指定平台项目", ["1", "3", "1", "carpet", "q"]),
            ("忽略", ["1", "4", "1", "1", "q"]),
        ]
        for label, values in scenarios:
            ctx = make_ctx(tmp_path, values)
            run_profiles_screen(ctx)
            text = out(ctx)
            assert "✗" in text, label
            assert path.read_bytes() == before, label
    finally:
        writable(path)


@WINDOWS_ONLY
def test_rename_readonly_source_reports_partial(tmp_path: Path) -> None:
    """只读清单改名：Windows 上能写新文件但删不掉旧的 -> 必须明确告警。

    这条是实测出来的平台差异：os.replace 可以替换只读文件，unlink 不行。
    """
    path = write_profile(tmp_path, "服务器A", 1)
    read_only(path)
    try:
        ctx = make_ctx(tmp_path, ["1", "r", "新名字", "q"])
        run_profiles_screen(ctx)
        text = out(ctx)
        assert "⚠ 新清单已写入，但旧的" in text
        assert (tmp_path / "profiles" / "新名字.json").exists()
        assert path.exists()
    finally:
        writable(path)


@WINDOWS_ONLY
def test_settings_save_failure_message(tmp_path: Path) -> None:
    """只读 settings.json：给 PRD 那句 ✗，内存值仍然生效（裁决）。"""
    path = tmp_path / "settings.json"
    save_settings(path, Settings())
    before = path.read_bytes()
    read_only(path)
    try:
        ctx = make_ctx(tmp_path, ["5", "4", "q"])
        run_settings_screen(ctx)
        text = out(ctx)
        assert "✗ 设置无法保存到" in text and "本次修改仅在当前运行期间有效。" in text
        assert path.read_bytes() == before
        assert ctx.settings.concurrency == 4
    finally:
        writable(path)


@WINDOWS_ONLY
def test_session_continues_after_failure(tmp_path: Path) -> None:
    """写盘失败后同一会话仍能继续操作（R3-A13 验收）。"""
    path = write_profile(tmp_path, "服务器A", 3)
    read_only(path)
    try:
        # 先失败一次（删除模组），再在同一个会话里执行一个只读操作（查看列表）
        ctx = make_ctx(tmp_path, ["1", "2", "1", "y", "1", "q", "q"])
        run_profiles_screen(ctx)
        text = out(ctx)
        assert "✗" in text
        assert "清单「服务器A」的模组（共 3 个，第 1/1 页）：" in text
    finally:
        writable(path)
    # 恢复可写后同一个文件仍然能被正常修改（失败没有污染状态）
    ctx2 = make_ctx(tmp_path, ["1", "2", "1", "y", "q"])
    run_profiles_screen(ctx2)
    assert "✓ 已删除 1 个模组" in out(ctx2)
    assert [entry.mod_id for entry in load_profile(path).mods] == ["m1", "m2"]


def test_new_profile_failure_message(tmp_path: Path, monkeypatch) -> None:
    """新建清单写盘失败 -> ✗ 文案，且没有半成品文件。"""

    def boom(*_args, **_kwargs):
        raise ProfileError("写不进去")

    monkeypatch.setattr("modcheck.cli.screens_profiles.save_profile", boom)
    ctx = make_ctx(tmp_path, ["n", "服务器B", "q"])
    run_profiles_screen(ctx)
    assert "✗ 创建失败：" in out(ctx)
    assert not (tmp_path / "profiles" / "服务器B.json").exists()


def test_settings_file_not_touched_when_load_fails(tmp_path: Path) -> None:
    """损坏的 settings.json 不会让设置屏崩（load_settings 已降级为默认值）。"""
    (tmp_path / "settings.json").write_text("{ broken", encoding="utf-8")
    ctx = make_ctx(tmp_path, ["q"])
    ctx.settings = load_settings(tmp_path / "settings.json")
    assert run_settings_screen(ctx) is not None
    assert ctx.settings.to_dict() == Settings().to_dict()
