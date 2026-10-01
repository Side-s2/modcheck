# -*- coding: utf-8 -*-
"""主 Agent 独立验证：HttpClient 的 POST 缓存键是否会因 payload 不同而串味。"""
import json, sys, tempfile
from pathlib import Path

ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))

from modcheck.cache import HttpCache
from modcheck.providers.http import HttpClient, HttpConfig, HttpResponse

calls = []

def fake_transport(method, url, headers, data, timeout):
    payload = json.loads(data.decode()) if data else None
    calls.append((method, url, payload))
    # 服务端按请求里的 hashes 返回对应结果
    if payload and "hashes" in payload:
        return HttpResponse(200, {"content-type": "application/json"},
                            json.dumps({h: {"project_id": "P_" + h, "version_number": "v_" + h}
                                        for h in payload["hashes"]}).encode())
    return HttpResponse(200, {}, b"{}")

tmp = Path(tempfile.mkdtemp(prefix="mvc-cache-"))
cache = HttpCache(tmp)
cfg = HttpConfig()
client = HttpClient(cfg, cache=cache, transport=fake_transport)

URL = "https://api.modrinth.com/v2/version_files"

r1 = client.post_json(URL, {"hashes": ["aaaa1111"], "algorithm": "sha1"})
r2 = client.post_json(URL, {"hashes": ["bbbb2222"], "algorithm": "sha1"})

print("第 1 次请求（hashes=[aaaa1111]）→", r1)
print("第 2 次请求（hashes=[bbbb2222]）→", r2)
print()
print("真实发出的请求次数:", len(calls), [c[2] for c in calls])
print()
ok1 = "aaaa1111" in r1
ok2 = "bbbb2222" in r2 and "aaaa1111" not in r2
print(f"  第1次结果正确: {ok1}")
print(f"  第2次结果正确（且未被第1次污染）: {ok2}")
print()
if ok1 and ok2:
    print("  ✅ POST 缓存键区分了 payload")
else:
    print("  ❌ BUG：POST 缓存键只用了 URL，不同 payload 命中同一条缓存 → 指纹反查会返回别的模组的结果")
    print("     第 2 次调用根本没有发出真实请求，直接吃了第 1 次的缓存。")

# 再验证：显式传 cache_key 是否能规避
client.reset_stats()
r3 = client.post_json(URL, {"hashes": ["cccc3333"]}, cache_key="k_ccc")
r4 = client.post_json(URL, {"hashes": ["dddd4444"]}, cache_key="k_ddd")
print()
print("显式传不同 cache_key 时：", r3, r4, "→", "✅ 正常" if "dddd4444" in r4 else "❌ 仍串味")
print(f"统计数据（真实请求, 缓存命中）: {client.stats}")

import shutil; shutil.rmtree(tmp, ignore_errors=True)
