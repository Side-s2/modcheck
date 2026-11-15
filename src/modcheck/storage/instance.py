"""Require one writer process per configuration directory."""
from __future__ import annotations

import errno
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from modcheck.errors import ConfigError


@contextmanager
def configuration_lock(directory: Path) -> Iterator[None]:
    """Hold an OS lock for the session, including during worker shutdown."""
    try:
        handle = (directory / ".modcheck.lock").open("a+b")
    except OSError as exc:
        raise ConfigError(f"无法锁定配置目录「{directory}」。请确认目录可写。") from exc
    with handle:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise ConfigError(f"配置目录「{directory}」正在被另一个 modcheck 实例使用。"
                                  "请关闭该实例后重试，或使用另一配置目录。") from exc
            raise ConfigError(f"无法锁定配置目录「{directory}」（{exc.strerror or exc}）。") from exc
        # 关闭句柄时释放锁。保留锁文件，避免其他进程锁住已被删除的旧文件。
        yield
