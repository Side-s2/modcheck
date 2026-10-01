# -*- coding: utf-8 -*-
"""对 mods_sample/ 的 30 个真实 jar 建立独立判定基准（oracle）。

路径与 modcheck 完全独立：直接算 sha1 → POST /v2/version_files 反查 → 用自己的 classify 判定。
产出: docs/research/results/11_ground_truth_mods_sample.json
"""
import hashlib, json, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "mods_sample"
UA = {"User-Agent": "modcheck-oracle/0.1", "Content-Type": "application/json"}
BASE = "https://api.modrinth.com/v2"
WINDOW = 25
TARGETS = [("26.3", "fabric"), ("26.1", "fabric")]


def get(path, **params):
    url = BASE + path + (("?" + urllib.parse.urlencode(params)) if params else "")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, payload):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers=UA, method="POST")
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))


def classify(slug, mc, loader):
    L, V = json.dumps([loader]), json.dumps([mc])
    a = get(f"/project/{slug}/version", loaders=L, version_type="release", limit=WINDOW)
    a2 = [] if a else get(f"/project/{slug}/version", loaders=L, limit=WINDOW)
    b = get(f"/project/{slug}/version", game_versions=V, loaders=L, version_type="release", limit=WINDOW)
    b2 = [] if b else get(f"/project/{slug}/version", game_versions=V, loaders=L, limit=WINDOW)
    if not a and not a2:
        return "BLOCKED", "NO_LOADER", {}
    if b and a and b[0]["id"] == a[0]["id"]:
        return "READY", "OK", {"latest": a[0]["version_number"]}
    if b:
        return "DEGRADED", "OLD_VERSION_ONLY", {
            "latest": (a[0] if a else a2[0])["version_number"],
            "latest_compat": b[0]["version_number"]}
    if b2:
        return "DEGRADED", "PRERELEASE_ONLY", {
            "channel": b2[0]["version_type"], "version": b2[0]["version_number"]}
    mcs = sorted({g for v in a for g in v["game_versions"]})
    return "BLOCKED", "NO_MC_VERSION", {"max_supported_mc": mcs[-1] if mcs else None}


def main() -> int:
    jars = sorted(SAMPLE.glob("*.jar"))
    print(f"发现 {len(jars)} 个 jar")
    entries = []
    for p in jars:
        sha1 = hashlib.sha1(p.read_bytes()).hexdigest()
        entries.append({"file": p.name, "sha1": sha1})

    # 分批反查（每批 10 个），验证批量指纹反查在真实规模下是否可靠
    resolved = {}
    for i in range(0, len(entries), 10):
        chunk = entries[i:i + 10]
        resp = post("/version_files", {"hashes": [e["sha1"] for e in chunk], "algorithm": "sha1"})
        for h, info in resp.items():
            resolved[h] = {"project_id": info["project_id"], "version_number": info["version_number"],
                           "version_type": info["version_type"], "game_versions": info["game_versions"],
                           "loaders": info["loaders"]}
    hit = sum(1 for e in entries if e["sha1"] in resolved)
    print(f"指纹反查命中 {hit}/{len(entries)}")

    result = {"generated_by": "11_oracle_mods_sample.py（独立实现）",
              "sample_size": len(entries), "hash_hit": hit, "cases": {}}
    for mc, loader in TARGETS:
        key = f"{mc}/{loader}"
        result["cases"][key] = {}
        print(f"--- {key} ---")
        for e in entries:
            info = resolved.get(e["sha1"])
            if not info:
                result["cases"][key][e["file"]] = {"slug": None, "status": "UNKNOWN", "reason": "HASH_MISS"}
                continue
            try:
                slug = get(f"/project/{info['project_id']}")["slug"]
            except Exception:
                slug = info["project_id"]
            st, reason, detail = classify(slug, mc, loader)
            result["cases"][key][e["file"]] = {"slug": slug, "installed": info["version_number"],
                                              "status": st, "reason": reason, "detail": detail}
            print(f"   {e['file'][:52]:54s} {slug:26s} {st:9s} {reason}")
        print()

    # 统计
    for key, items in result["cases"].items():
        c = {}
        for v in items.values():
            c[v["status"]] = c.get(v["status"], 0) + 1
        print(f"{key}: {c}")

    out = ROOT / "docs" / "research" / "results" / "11_ground_truth_mods_sample.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {out}")
    return 0


raise SystemExit(main())
