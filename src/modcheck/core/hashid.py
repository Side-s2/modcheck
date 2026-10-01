"""文件指纹：流式 sha1 + jar 粗判。

sha1 是识别模组的**第一优先手段**（基线 §11.3）：把 jar 的 sha1 批量提交给
Modrinth 的 /version_files，可以直接得到 project_id 与"用户当前装的确切版本"，
而且完全不受 PCL 改名影响。
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

#: 读文件的块大小（64 KB，兼顾内存与系统调用次数）
CHUNK_SIZE: Final[int] = 65536
#: zip 的魔数
ZIP_MAGIC: Final[bytes] = b"PK"


def sha1_of_file(path: Path, *, chunk: int = CHUNK_SIZE) -> str:
    """流式计算文件的 sha1（大文件不爆内存）。"""
    digest = hashlib.sha1()
    with Path(path).open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def is_probably_jar(path: Path) -> bool:
    """粗判是不是 jar：扩展名 + 开头两个字节是 PK。"""
    target = Path(path)
    if not target.name.lower().endswith(".jar"):
        return False
    try:
        with target.open("rb") as handle:
            return handle.read(2) == ZIP_MAGIC
    except OSError:
        return False


__all__ = ["CHUNK_SIZE", "ZIP_MAGIC", "sha1_of_file", "is_probably_jar"]
