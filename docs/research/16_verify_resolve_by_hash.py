# -*- coding: utf-8 -*-
"""核实：ModrinthProvider.resolve_by_hash 是否因为显式 cache_key 而规避了 D28 的默认键问题。"""
import json, sys, tempfile
from pathlib import Path

ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))

from modcheck.cache import HttpCache
from modcheck.providers.http import HttpClient, HttpConfig, HttpResponse
from modcheck.providers.modrinth import ModrinthProvider

sent = []

def fake_transport(method, url, headers, data, timeout):
    body = json.loads(data.decode()) if data else None
    sent.append((method, url.split("?")[0], body))
    if url.endswith("/version_files"):
        return HttpResponse(200, {}, json.dumps({h: {"id": "V_" + h, "project_id": "P_" + h,
                                                     "version_number": "n_" + h, "name": "",
                                                     "date_published": "2026-01-01T00:00:00Z",
                                                     "version_type": "release", "game_versions": [],
                                                     "loaders": [], "files": []}
                                                 for h in body["hashes"]}).encode())
    return HttpResponse(200, {}, b"[]")

tmp = Path(tempfile.mkdtemp(prefix="mvc-vf-"))
client = HttpClient(HttpConfig(), cache=HttpCache(tmp), transport=fake_transport)
prov = ModrinthProvider(client)

r1 = prov.resolve_by_hash(["a" * 40, "b" * 40])
r2 = prov.resolve_by_hash(["c" * 40, "d" * 40])
r3 = prov.resolve_by_hash(["a" * 40, "b" * 40])          # 重复第 1 批 -> 应命中缓存

print("第1批返回 keys:", sorted(r1))
print("第2批返回 keys:", sorted(r2))
print("第3批(重复第1批) keys:", sorted(r3))
print()
print("真实发出的 /version_files 请求数:", sum(1 for s in sent if s[1].endswith("/version_files")))
print("请求体:", [s[2]["hashes"] for s in sent if s[1].endswith("/version_files")])
print()
ok2 = set(r2) == {"c" * 40, "d" * 40}
ok3 = set(r3) == {"a" * 40, "b" * 40}
print(f"  ✅ 第2批未被第1批污染: {ok2}")
print(f"  ✅ 第3批命中缓存且结果正确: {ok3}")
print(f"  统计 (真实请求, 缓存命中): {client.stats}")

# 对照：不走 resolve_by_hash，直接用 client.post_json（默认键）
c2 = HttpClient(HttpConfig(), cache=HttpCache(tmp), transport=fake_transport)
c2.post_json("https://api.modrinth.com/v2/version_files", {"hashes": ["e" * 40]})
before = len(sent)
c2.post_json("https://api.modrinth.com/v2/version_files", {"hashes": ["f" * 40]})
after = len(sent)
print()
print(f"  对照（默认键，不带 cache_key）: 第2次调用是否真的发了请求 = {after > before}")
print("  → " + ("默认键仍然串味（D28 依然成立，只是当前唯一的 POST 调用点已用显式 cache_key 规避）"
                if after == before else "默认键也没问题"))

import shutil; shutil.rmtree(tmp, ignore_errors=True)
