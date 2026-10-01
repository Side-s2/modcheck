# -*- coding: utf-8 -*-
"""量化 D40 的影响：目标 MC 下，有多少 🟡 其实是『同一版本号的不同 MC 构建』（应判 🟢）。
带节流与重试（Modrinth 300/分，且我们刚被 SSL 中断过）。"""
import json, json as _json, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
UA = {"User-Agent": "modcheck-verify/0.1"}
BASE = "https://api.modrinth.com/v2"
WINDOW = 25
_last = [0.0]

def get(path, **params):
    url = BASE + path + (("?" + urllib.parse.urlencode(params)) if params else "")
    for attempt in range(4):
        wait = 0.30 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return json.loads(r.read().decode())
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            if attempt == 3:
                raise
            time.sleep(1.5 * (attempt + 1))
    return None

GT = json.loads((ROOT / "docs/research/results/11_ground_truth_mods_sample.json").read_text(encoding="utf-8"))
slugs = sorted({v["slug"] for v in GT["cases"]["26.3/fabric"].values() if v.get("slug")})

for mc in ("26.3", "26.1"):
    print("=" * 96); print(f"目标 MC {mc} / fabric"); print("=" * 96)
    flips, stay, ready, other = [], [], 0, 0
    for slug in slugs:
        try:
            L, V = json.dumps(["fabric"]), json.dumps([mc])
            a = get(f"/project/{slug}/version", loaders=L, version_type="release", limit=WINDOW)
            b = get(f"/project/{slug}/version", game_versions=V, loaders=L, version_type="release", limit=WINDOW)
        except Exception as e:
            print(f"      ! {slug}: {type(e).__name__}"); other += 1; continue
        if not a:
            other += 1; continue
        if b and b[0]["id"] == a[0]["id"]:
            ready += 1; continue
        if not b:
            continue
        if b[0]["version_number"] == a[0]["version_number"]:
            flips.append((slug, a[0]["version_number"], tuple(a[0]["game_versions"][:2]), tuple(b[0]["game_versions"][:2])))
        else:
            stay.append((slug, a[0]["version_number"], b[0]["version_number"]))
    print(f"  🟢 本来就绪 {ready} ｜ 🟡 假黄（D40 会翻成 🟢）{len(flips)} ｜ 🟡 真需拍板 {len(stay)} ｜ 其它 {other}")
    for s, ver, agv, bgv in flips:
        print(f"      [假黄] {s:26s} {ver:22s} 最新版支持{list(agv)} 兼容版支持{list(bgv)}")
    for s, lv, cv in stay:
        print(f"      [真黄] {s:26s} 最新 {lv:24s} -> 适用 {cv}")
    print()
