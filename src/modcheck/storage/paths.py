"""配置目录探测（便携优先，其次用户目录，最后回退）。

优先级（T-15 契约）：
    --config-dir > 环境变量 MODCHECK_CONFIG_DIR > 便携目录（exe 同级 config/，可写时）
    > Windows %APPDATA%\\modcheck / Linux ~/.config/modcheck

"便携模式"在两种场景都生效：
    * 打包产物：exe 所在目录（Nuitka onefile 下 sys.executable 指向临时目录，所以用 sys.argv[0]）；
    * 源码 / 启动器（modcheck.cmd、modcheck.sh）：**项目根**（含 src\ 的那一层）。

⚠️ 源码模式以前直接回退到 %APPDATA%（C 盘），用户实测反馈"程序把文件写到 C 盘、
还因此需要管理员权限"。配置文件跟程序放一起才符合"绿色软件"的预期，所以现在两条路径都便携。
只有当便携目录**不可写**（例如放在 Program Files）时才回退到用户目录。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Mapping

#: 覆盖配置目录的环境变量
ENV_CONFIG_DIR = "MODCHECK_CONFIG_DIR"
#: 便携模式的子目录名
PORTABLE_DIRNAME = "config"


def _portable_dir(exe_dir: Path | None) -> Path | None:
    """返回便携配置目录（仅当提供了 exe 所在目录时）。"""
    if exe_dir is None:
        return None
    return Path(exe_dir) / PORTABLE_DIRNAME


def is_writable(path: Path) -> bool:
    """真写一个临时文件再删掉，判断目录是否可写。"""
    target = Path(path)
    try:
        target.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(dir=str(target), prefix=".probe-")
        os.close(handle)
        Path(name).unlink(missing_ok=True)
        return True
    except OSError:
        return False


def fallback_config_dir() -> Path:
    """系统默认的用户级配置目录。"""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "modcheck"
        return Path.home() / "AppData" / "Roaming" / "modcheck"
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "modcheck"
    return Path.home() / ".config" / "modcheck"


def resolve_config_dir(cli_arg: str | None, *, env: Mapping[str, str] | None = None,
                       exe_dir: Path | None = None) -> Path:
    """按优先级解析配置目录（不做可写性回退，回退交给 ensure_config_dir）。"""
    env = os.environ if env is None else env
    if cli_arg:
        return Path(cli_arg).expanduser()
    from_env = env.get(ENV_CONFIG_DIR)
    if from_env:
        return Path(from_env).expanduser()
    portable = _portable_dir(exe_dir)
    if portable is not None and is_writable(portable):
        return portable
    return fallback_config_dir()


def ensure_config_dir(path: Path) -> tuple[Path, bool]:
    """确保配置目录可写；不可写时回退到用户目录。

    返回：
        (最终目录, 是否发生了回退)
    """
    target = Path(path)
    if is_writable(target):
        return target, False
    fallback = fallback_config_dir()
    if fallback == target:
        return target, False
    is_writable(fallback)
    return fallback, True


def _source_root() -> Path | None:
    """源码/启动器模式下的"程序目录" = 项目根（包含 src\ 的那一层）。

    本文件位于 <root>/src/modcheck/storage/paths.py，所以 parents[3] 就是 <root>。
    只有当这一层真的叫 src 时才认（否则说明包被装到了 site-packages 之类的地方，
    那时乱猜目录比回退到用户目录更糟）。
    """
    here = Path(__file__).resolve()
    try:
        src = here.parents[2]
        root = here.parents[3]
    except IndexError:                     # 目录层级比预期浅
        return None
    return root if src.name == "src" else None


def is_packaged() -> bool:
    """是否运行在打包产物里。

    Nuitka **不设置** sys.frozen（实测 4.2.2 三种模式都没有），它用模块级
    __compiled__ 标记；PyInstaller 才设 sys.frozen。两个都要认。
    """
    return "__compiled__" in globals() or bool(getattr(sys, "frozen", False))


def detect_exe_dir() -> Path | None:
    """返回"程序所在目录"：打包产物 = exe 目录，源码运行 = 项目根。

    ⚠️ 实测（2026-10-01，Nuitka 4.2.2 / Python 3.11.9）：
      * Nuitka standalone：sys.executable 是 <dist>/python.exe（恰好同目录，能用）；
      * Nuitka **onefile**：sys.executable 指向 %TEMP%/onefile_xxx/python.exe，
        那是解包临时目录，**进程退出即删** —— 用它会把用户清单写丢；
      * sys.argv[0] 在两种模式下都是真正的 exe 路径，所以**必须优先用它**。
    """
    if not is_packaged():
        return _source_root()
    raw = (sys.argv[0] if sys.argv and sys.argv[0] else "") or sys.executable
    try:
        return Path(raw).resolve().parent
    except OSError:
        return Path(sys.executable).resolve().parent


def cache_dir(config_dir: Path) -> Path:
    """缓存目录：<config>/cache。"""
    return Path(config_dir) / "cache"


def http_cache_dir(config_dir: Path) -> Path:
    """HTTP 缓存目录：<config>/cache/http。"""
    return cache_dir(config_dir) / "http"


def profiles_dir(config_dir: Path) -> Path:
    """清单目录：<config>/profiles。"""
    return Path(config_dir) / "profiles"


def settings_path(config_dir: Path) -> Path:
    """设置文件路径：<config>/settings.json。"""
    return Path(config_dir) / "settings.json"


__all__ = ["ENV_CONFIG_DIR", "PORTABLE_DIRNAME", "is_writable", "fallback_config_dir",
           "resolve_config_dir", "ensure_config_dir", "detect_exe_dir", "is_packaged",
           "cache_dir", "http_cache_dir", "profiles_dir", "settings_path"]
