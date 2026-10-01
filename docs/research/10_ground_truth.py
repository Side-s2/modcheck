# -*- coding: utf-8 -*-
"""独立判定基准（oracle）：用主 Agent 实测验证过的算法，对 .demo_mods 里的真实模组
计算在若干「目标 MC 版本 × 加载器」下的期望状态，供日后独立验证 modcheck 的输出。

本脚本刻意不 import modcheck，是一条完全独立的实现路径（交叉验证）。
"""
import json, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UA = {"User-Agent": "modcheck-oracle/0.1"}
BASE = "https://api.modrinth.com/v2"
WINDOW = 25

TARGETS = [("26.3", "fabric"), ("26.1", "fabric"), ("26.3", "neoforge"), ("26.3", "forge")]


def get(path, **params):
    url = BASE + path + (("?" + urllib.parse.urlencode(params)) if params else "")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


def classify(slug: str, mc: str, loader: str) -> dict:
    L = json.dumps([loader]); V = json.dumps([mc])
    a = get(f"/project/{slug}/version", loaders=L, version_type="release", limit=WINDOW)
    a2 = get(f"/project/{slug}/version", loaders=L, limit=WINDOW) if not a else []
    b = get(f"/project/{slug}/version", game_versions=V, loaders=L, version_type="release", limit=WINDOW)
    b2 = get(f"/project/{slug}/version", game_versions=V, loaders=L, limit=WINDOW) if not b else []

    def first(xs):
        return xs[0] if xs else None

    if not a and not a2:
        loaders = sorted({l for v in
                          (get(f"/project/{slug}/version", limit=5) or []) for l in v["loaders"]})
        return {"status": "BLOCKED", "reason": "NO_LOADER", "detail": {"available_loaders": loaders}}
    if b and a and b[0]["id"] == a[0]["id"]:
        return {"status": "READY", "reason": "OK",
                "detail": {"latest": a[0]["version_number"], "date": a[0]["date_published"][:10]}}
    if b:
        return {"status": "DEGRADED", "reason": "OLD_VERSION_ONLY",
                "detail": {"latest": (a[0] if a else a2[0])["version_number"],
                           "latest_compat": b[0]["version_number"],
                           "latest_compat_date": b[0]["date_published"][:10]}}
    if b2:
        return {"status": "DEGRADED", "reason": "PRERELEASE_ONLY",
                "detail": {"channel": b2[0]["version_type"], "version": b2[0]["version_number"]}}
    mcs = sorted({g for v in a for g in v["game_versions"]})
    return {"status": "BLOCKED", "reason": "NO_MC_VERSION",
            "detail": {"max_supported_mc": mcs[-1] if mcs else None}}


def main() -> int:
    manifest = json.loads((ROOT / ".demo_mods" / "_manifest.json").read_text(encoding="utf-8"))
    result = {"generated_by": "10_ground_truth.py（独立实现，不 import modcheck）",
              "window": WINDOW, "cases": {}}
    for mc, loader in TARGETS:
        key = f"{mc}/{loader}"
        result["cases"][key] = {}
        print(f"--- 目标 {key} ---")
        for item in manifest:
            try:
                r = classify(item["slug"], mc, loader)
            except Exception as e:
                r = {"status": "UNKNOWN", "reason": "ERROR", "detail": {"error": f"{type(e).__name__}: {e}"}}
            result["cases"][key][item["slug"]] = {"file": item["file"], **r}
            d = r["detail"]
            print(f"   {item['slug']:12s} {r['status']:9s} {r['reason']:18s} {d}")
        print()
    # 额外基准：不存在的项目 / 只有文件名的情况
    result["extra"] = {
        "no-such-mod-xyz": {"expect": "BLOCKED:NOT_FOUND", "note": "搜索无精确同名 → 非交互下应为 UNMATCHED 还是 NOT_FOUND，见 PRD §4.3"},
        "expected_sha1_map": {i["file"]: i["sha1"] for i in manifest},
    }
    out = ROOT / "docs" / "research" / "results" / "10_ground_truth.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {out}")
    return 0


raise SystemExit(main())
