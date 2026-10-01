# -*- coding: utf-8 -*-
"""验证 1) jar 内部元数据可靠性 2) latest_all 的 version_number 分组修正"""
import io, json, re, urllib.parse, urllib.request, zipfile

UA = {"User-Agent": "modcheck-feasibility/0.1"}
BASE = "https://api.modrinth.com/v2"
out = []
def p(s=""): out.append(str(s))

def get(path, **params):
    url = BASE + path + (("?" + urllib.parse.urlencode(params)) if params else "")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def get_bytes(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read()

p("=" * 90)
p("【验证 A】jar 内部元数据是否可靠（决定 modid / 支持版本 / 加载器）")
p("=" * 90)

CASES = [
    ("carpet", "fabric", "fabric.mod.json"),
    ("jei", "fabric", "fabric.mod.json"),
    ("jei", "neoforge", "META-INF/neoforge.mods.toml"),
    ("jei", "forge", "META-INF/mods.toml"),
]

for slug, loader, member in CASES:
    try:
        versions = get(f"/project/{slug}/version")
    except Exception as e:
        p(f"{slug}/{loader}: 取版本失败 {e}"); continue
    cand = [v for v in versions if loader in v["loaders"] and v["files"]]
    if not cand:
        p(f"{slug}/{loader}: 无该加载器版本"); continue
    v = max(cand, key=lambda x: x["date_published"])
    f = next((x for x in v["files"] if x.get("primary")), v["files"][0])
    p(f"\n--- {slug} / {loader} / {v['version_number']} ---")
    p(f"    文件名: {f['filename']}  大小: {f['size']} bytes")
    try:
        blob = get_bytes(f["url"])
        zf = zipfile.ZipFile(io.BytesIO(blob))
        names = zf.namelist()
        p(f"    实际条目 {member}: {member in names}")
        if member.lower().endswith(".json"):
            data = json.loads(zf.read(member).decode("utf-8"))
            p(f"    id={data.get('id')!r} name={data.get('name')!r} version={data.get('version')!r}")
            dep = data.get("depends", {})
            p(f"    depends.minecraft={dep.get('minecraft')!r}  depends keys={list(dep)[:6]}")
            p(f"    loaders字段={data.get('loaders')!r}  environment={data.get('environment')!r}")
        else:
            txt = zf.read(member).decode("utf-8", "replace")
            p("    TOML 头部摘录:")
            for line in txt.splitlines()[:24]:
                p("      " + line)
    except Exception as e:
        p(f"    下载/解析失败: {type(e).__name__}: {e}")

p()
p("=" * 90)
p("【验证 B】latest_all 必须按 version_number 分组（journeymap 的 paper/fabric 同版本号问题）")
p("=" * 90)
versions = get("/project/journeymap/version")
rel = [v for v in versions if v["version_type"] == "release"]
groups = {}
for v in rel:
    groups.setdefault(v["version_number"], []).append(v)
for vn in list(groups)[:8]:
    items = groups[vn]
    loaders = sorted({l for it in items for l in it["loaders"]})
    gv = sorted({g for it in items for g in it["game_versions"]})[:3]
    dates = sorted(it["date_published"] for it in items)
    p(f"  version_number={vn:26s} 条目数={len(items)} loaders={loaders} game_versions(前3)={gv} earliest={dates[0][:10]}")

p()
p("  按 version_number 分组的正确 latest_all（取最早发布时间代表该版本，避免多加载器互相抢占）:")
best = max(groups.items(), key=lambda kv: min(it["date_published"] for it in kv[1]))
p(f"    latest_all(version_number) = {best[0]}  loaders={sorted({l for it in best[1] for l in it['loaders']})}")

for mc in ("26.3",):
    comp = {vn: any(mc in it["game_versions"] and "fabric" in it["loaders"] for it in items) for vn, items in groups.items()}
    ok = [vn for vn, c in comp.items() if c]
    p(f"    目标 {mc}/fabric 下兼容的 version_number 数量 = {len(ok)}，最新兼容 = {ok[0] if ok else None}")
    p(f"    → 判定应为: {'READY（最新版本号本身兼容）' if best[0] in comp and comp[best[0]] else 'DEGRADED'}")

open(r"D:\Programme\python_prgram\mod-version-checker\.probe_result.txt", "w", encoding="utf-8").write("\n".join(out))
print("OK, written", len(out), "lines")
