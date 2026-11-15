"""通过同目录的独立临时文件替换目标。"""
from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, TextIO


@contextmanager
def atomic_text(path: Path, *, newline: str | None = None) -> Iterator[TextIO]:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", dir=target.parent, prefix=".modcheck-", suffix=".tmp",
        encoding="utf-8", newline=newline, delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            yield handle
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
