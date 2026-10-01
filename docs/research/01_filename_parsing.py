# -*- coding: utf-8 -*-
"""主 Agent 技术验证：真实调用 Modrinth，验证文件名解析 + 完全同名匹配 + 三态判定。"""
import json, re, sys, time, urllib.parse, urllib.request

UA = {"User-Agent": "modcheck-feasibility/0.1 (contact: dev@example.invalid)"}
BASE = "https://api.modrinth.com/v2"

def get(path, **params):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8")), dict(r.headers)

def norm(s):
    return re.sub(r"[-_. ]+", "", (s or "").lower())

# ---- 官方 MC 版本清单（用于文件名解析锚点）----
manifest, _ = get_manifest = None, None
req = urllib.request.Request("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json", headers=UA)
with urllib.request.urlopen(req, timeout=25) as r:
    manifest = json.loads(r.read().decode("utf-8"))
RELEASES = [v["id"] for v in manifest["versions"] if v["type"] == "release"]
REL_SET = set(RELEASES)
print("官方正式版数量:", len(RELEASES), "| 最近5个:", RELEASES[:5])

LOADER_PREFIXES = ("fabric-", "forge-", "neoforge-", "quilt-", "fabric", "forge", "neoforge")

def parse_jar_name(filename):
    """PCL / 通用格式解析。返回 dict。"""
    stem = filename[:-4] if filename.lower().endswith(".jar") else filename
    # 去掉 .disabled
    for suf in (".disabled", ".old", ".bak"):
        if stem.lower().endswith(suf):
            stem = stem[: -len(suf)]
    cn = None
    m = re.match(r"^\s*((?:\[[^\]]*\]\s*)+)(.*)$", stem)
    if m:
        groups = re.findall(r"\[([^\]]*)\]", m.group(1))
        cn = next((g.strip() for g in groups if g.strip()), None)
        stem = m.group(2).strip()
    # 按 + 切分：左=名称+MC版本，右=模组版本
    left, plus, right = stem.partition("+")
    mod_version = right.strip() or None
    if not plus:
        mod_version = None
    # 从左段右侧找已知 MC 版本 token
    parts = left.split("-")
    mc_version = None
    idx = None
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] in REL_SET:
            mc_version = parts[i]; idx = i; break
    name_parts = parts[:idx] if idx is not None else parts
    name = "-".join(name_parts).strip()
    if not plus and idx is not None and idx < len(parts) - 1:
        # 无 + 时，MC 版本右侧剩下的就是模组版本
        mod_version = "-".join(parts[idx + 1:]).strip() or None
    loader_hint = None
    low = name.lower()
    for p in ("fabric-", "forge-", "neoforge-", "quilt-"):
        if low.startswith(p):
            loader_hint = p[:-1]; name = name[len(p):]; break
    return {"cn": cn, "name": name, "mc": mc_version, "modver": mod_version, "loader": loader_hint}

FILES = [
    "[地毯] fabric-carpet-26.1+v260402.jar",
    "fabric-api-0.92.2+1.20.1.jar",
    "lithium-fabric-0.12.1.jar",
    "ferritecore-6.0.1-fabric.jar",
    "journeymap-1.20.1-5.9.18-fabric.jar",
    "chunky-fabric-1.3.146.jar",
    "spark-1.10.53-fabric.jar",
    "cloth-config-11.1.106-fabric.jar",
    "modernfix-fabric-5.19.4+mc1.20.1.jar",
    "sodium-fabric-0.5.8+mc1.20.1.jar",
    "jei-1.20.1-fabric-15.2.0.27.jar",
    "servercore-fabric-1.4.6+1.20.1.jar",
    "c2me-fabric-mc1.20.1-0.2.0+alpha.11.50.jar",
    "fabric-carpet-26.3+v260901.jar",
]

print()
print("=" * 100)
print("【一】文件名解析验证")
print("=" * 100)
parsed = []
for f in FILES:
    p = parse_jar_name(f)
    parsed.append((f, p))
    print(f"{f:52s} -> name={p['name']:22s} mc={str(p['mc']):8s} modver={str(p['modver']):20s} cn={p['cn']}")

print()
print("=" * 100)
print("【二】完全同名匹配验证（Modrinth search）")
print("=" * 100)
results = []
for f, p in parsed:
    term = p["name"]
    try:
        data, _ = get("/search", query=term, limit=10, facets='[["project_type:mod"]]')
    except Exception as e:
        print(f"{term:24s} SEARCH FAILED: {e}")
        continue
    hits = data.get("hits", [])
    exact = [h for h in hits if norm(h["slug"]) == norm(term) or norm(h["title"]) == norm(term)]
    status = "EXACT-1" if len(exact) == 1 else ("EXACT-N" if len(exact) > 1 else "NO-EXACT")
    top = ", ".join(f"{h['slug']}" for h in hits[:3])
    print(f"{term:24s} {status:9s} exact={[h['slug'] for h in exact]}  top3=[{top}]")
    results.append((f, p, exact))

print()
print("=" * 100)
print("【三】三态判定验证（目标 MC 26.3 / 26.1，加载器 fabric）")
print("=" * 100)

def evaluate(slug, mc, loader):
    try:
        versions, _ = get(f"/project/{slug}/version")
    except Exception as e:
        return ("ERROR", str(e))
    if not versions:
        return ("NONE", "")
    rel = [v for v in versions if v["version_type"] == "release"]
    def compat(v):
        return mc in v["game_versions"] and loader in v["loaders"]
    all_sorted = sorted(versions, key=lambda v: v["date_published"], reverse=True)
    latest_all = all_sorted[0]
    if compat(latest_all):
        return ("READY", f"latest={latest_all['version_number']}")
    rel_ok = [v for v in rel if compat(v)]
    if rel_ok:
        lc = max(rel_ok, key=lambda v: v["date_published"])
        return ("DEGRADED", f"latest_all={latest_all['version_number']} latest_compat={lc['version_number']}")
    beta_ok = [v for v in versions if v["version_type"] != "release" and compat(v)]
    if beta_ok:
        return ("DEGRADED-PRE", f"latest_all={latest_all['version_number']}")
    has_loader = [v for v in versions if loader in v["loaders"]]
    if not has_loader:
        return ("BLOCKED:NO_LOADER", f"loaders={sorted({l for v in versions for l in v['loaders']})[:6]}")
    mcs = sorted({g for v in has_loader for g in v["game_versions"]})
    return ("BLOCKED:NO_MC", f"latest_all={latest_all['version_number']} mc_count={len(mcs)} has_{mc}={mc in mcs}")

for mc in ("26.3", "26.1"):
    print(f"--- 目标 MC {mc} / fabric ---")
    for f, p, exact in results:
        if not exact:
            continue
        slug = exact[0]["slug"]
        st, info = evaluate(slug, mc, "fabric")
        print(f"  {slug:22s} {st:18s} {info}")
    print()
