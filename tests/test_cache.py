"""T-14 缓存测试：TTL、原子写、坏数据自愈。"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from modcheck.cache import CacheInfo, HttpCache, url_key
from fakes import FakeClock


def test_url_key_is_stable_and_prefixed() -> None:
    """key = sha1(url)，带 u_ 前缀。"""
    first = url_key("https://x/y")
    assert first == url_key("https://x/y")
    assert first.startswith("u_")
    assert first != url_key("https://x/z")


def test_put_get_round_trip(tmp_path: Path) -> None:
    """写入后能读回，且不留 .tmp 文件（原子写）。"""
    cache = HttpCache(tmp_path)
    cache.put("k1", {"a": "中文"}, url="https://x")
    assert cache.get("k1", 60) == {"a": "中文"}
    assert [p.name for p in tmp_path.iterdir()] == ["k1.json"]


def test_ttl_expiry(tmp_path: Path) -> None:
    """TTL 过期后返回 None。"""
    clock = FakeClock()
    cache = HttpCache(tmp_path, clock=clock.clock)
    cache.put("k1", {"a": 1})
    clock.now += 10
    assert cache.get("k1", 60) == {"a": 1}
    clock.now += 100
    assert cache.get("k1", 60) is None


def test_corrupted_cache_is_dropped(tmp_path: Path) -> None:
    """坏 JSON -> 返回 None 且删掉坏文件，绝不抛异常（PRD E21）。"""
    cache = HttpCache(tmp_path)
    path = cache.path_of("bad")
    path.write_text("{not json", encoding="utf-8")
    assert cache.get("bad", 60) is None
    assert not path.exists()


def test_non_dict_entry_is_dropped(tmp_path: Path) -> None:
    """结构不对的缓存条目同样丢弃。"""
    cache = HttpCache(tmp_path)
    path = cache.path_of("weird")
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert cache.get("weird", 60) is None
    assert not path.exists()


def test_info_and_clear(tmp_path: Path) -> None:
    """统计与清理（older_than 按文件 mtime 的真实时间算）。"""
    cache = HttpCache(tmp_path)
    cache.put("a", 1)
    cache.put("b", 2)
    old = time.time() - 3600
    os.utime(cache.path_of("a"), (old, old))
    info = cache.info()
    assert isinstance(info, CacheInfo)
    assert info.files == 2
    assert info.bytes > 0
    assert info.oldest is not None and info.newest is not None
    removed = cache.clear(older_than=600)
    assert removed == 1
    assert cache.info().files == 1
    assert cache.clear() == 1
    assert cache.info().files == 0


def test_missing_root_is_tolerated(tmp_path: Path) -> None:
    """目录不存在时 get/info/clear 都不抛。"""
    cache = HttpCache(tmp_path / "nope")
    assert cache.get("x", 60) is None
    assert cache.info().files == 0
    assert cache.clear() == 0
