"""文件缓存：TTL + 原子写 + 坏数据自愈（基线 §12）。

约定：
  * 缓存条目是 JSON 文本，结构 {key, url, fetched_at, body}；
  * 写入一律"先写 .tmp 再 os.replace"，断电也不会留下半截文件；
  * 读取时 JSON 解析失败 -> **当作未命中**并把坏文件删掉，绝不报错（PRD E21）。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Final

#: 缓存文件名的前缀（一眼能看出是 URL 缓存）
URL_KEY_PREFIX: Final[str] = "u_"


def url_key(url: str) -> str:
    """缓存键 = sha1(url)，带 "u_" 前缀。"""
    return URL_KEY_PREFIX + hashlib.sha1(url.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CacheInfo:
    """缓存目录概况。"""

    files: int
    bytes: int
    oldest: float | None
    newest: float | None


class HttpCache:
    """简单的文件缓存（一个 key 一个文件）。"""

    def __init__(self, root: Path, *, clock: Callable[[], float] = time.time) -> None:
        self.root = Path(root)
        self._clock = clock

    # ---------------------------------------------------------------- 路径
    def path_of(self, key: str) -> Path:
        """key 对应的缓存文件路径。"""
        return self.root / (key + ".json")

    # ---------------------------------------------------------------- 读写
    def get(self, key: str, ttl: float) -> Any | None:
        """读缓存；未命中 / 过期 / 坏数据都返回 None，绝不抛异常。"""
        path = self.path_of(key)
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except FileNotFoundError:
            return None
        except (OSError, ValueError, UnicodeDecodeError):
            self._drop(path)
            return None
        if not isinstance(payload, dict):
            self._drop(path)
            return None
        try:
            fetched_at = float(payload.get("fetched_at", 0))
        except (TypeError, ValueError):
            self._drop(path)
            return None
        if ttl > 0 and self._clock() - fetched_at > ttl:
            return None
        return payload.get("body")

    def put(self, key: str, payload: Any, *, url: str = "") -> None:
        """原子写入缓存条目；写不进去也不抛（缓存只是加速手段）。"""
        entry = {"key": key, "url": url, "fetched_at": self._clock(), "body": payload}
        path = self.path_of(key)
        tmp = path.with_name(path.name + ".tmp")
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with tmp.open("w", encoding="utf-8") as handle:
                json.dump(entry, handle, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError:
            self._drop(tmp)

    # ---------------------------------------------------------------- 维护
    def info(self) -> CacheInfo:
        """统计文件数、总字节与最早/最新时间。"""
        files = 0
        size = 0
        oldest: float | None = None
        newest: float | None = None
        try:
            for path in self.root.glob("*.json"):
                try:
                    stat = path.stat()
                except OSError:
                    continue
                files += 1
                size += stat.st_size
                oldest = stat.st_mtime if oldest is None else min(oldest, stat.st_mtime)
                newest = stat.st_mtime if newest is None else max(newest, stat.st_mtime)
        except OSError:
            pass
        return CacheInfo(files=files, bytes=size, oldest=oldest, newest=newest)

    def clear(self, *, older_than: float | None = None) -> int:
        """删除缓存文件；older_than 给出时只删更早的。返回删除数量。"""
        removed = 0
        # 文件 mtime 是真实墙钟时间，所以这里用 time.time() 而不是注入的 clock
        limit = None if older_than is None else time.time() - older_than
        try:
            candidates = list(self.root.glob("*.json"))
        except OSError:
            return 0
        for path in candidates:
            try:
                if limit is not None and path.stat().st_mtime >= limit:
                    continue
                path.unlink()
                removed += 1
            except OSError:
                continue
        return removed

    # ---------------------------------------------------------------- 内部
    def _drop(self, path: Path) -> None:
        """删除坏文件（失败也无所谓）。"""
        try:
            path.unlink()
        except OSError:
            pass


__all__ = ["URL_KEY_PREFIX", "url_key", "CacheInfo", "HttpCache"]
