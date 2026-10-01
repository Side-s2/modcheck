# -*- coding: utf-8 -*-
"""用 limit 过滤方案实现完整判定算法，并与全量基准结果比对。"""
import json, time, urllib.parse, urllib.request
UA = {"User-Agent": "modcheck-feasibility/0.1"}
BASE = "https://api.modrinth.com/v2"
out = []
def p(*s): out.append(" ".join(str(x) for x in s))

REQ = {"n": 0, "bytes": 0}
def get(path, params=None):
    url = BASE + path + (("?" + urllib.parse.urlencode(params)) if params else "")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        b = r.read()
    REQ["n"] += 1; REQ["bytes"] += len(b)
    return json.loads(b)

WINDOW = 25

def newest(versions, channel_ok):
    for v in versions:                      # API 已按时间倒序
        if channel_ok(v["version_type"]):
            return v
    return None

def evaluate(slug, mc, loader):
    """只用小请求的判定算法。"""
    a = get(f"/project/{slug}/version", {"loaders": f'["{loader}"]', "limit": WINDOW})
    b = get(f"/project/{slug}/version",
            {"game_versions": f'["{mc}"]', "loaders": f'["{loader}"]', "limit": WINDOW})
    rel = lambda t: t == "release"
    any_c = lambda t: True
    latest_loader_rel = newest(a, rel)
    latest_loader_any = newest(a, any_c)
    compat_rel = newest(b, rel)
    compat_any = newest(b, any_c)
    if latest_loader_any is None:
        return "BLOCKED:NO_LOADER", "该项目没有任何 %s 版本" % loader
    if compat_rel and latest_loader_rel and compat_rel["id"] == latest_loader_rel["id"]:
        return "READY", f'最新 {loader} 正式版 {latest_loader_rel["version_number"]} 支持 {mc}'
    if compat_rel:
        return "DEGRADED:OLD_VERSION_ONLY", \
               f'最新 {loader} 版 {(latest_loader_rel or latest_loader_any)["version_number"]} 不支持 {mc}；最新兼容版 {compat_rel["version_number"]}'
    if compat_any:
        return "DEGRADED:PRERELEASE_ONLY", \
               f'仅测试版可用：{compat_any["version_number"]} ({compat_any["version_type"]})'
    has_l = [v for v in a]
    mcs = sorted({g for v in has_l for g in v["game_versions"]})
    return "BLOCKED:NO_MC_VERSION", f'最高只支持到 {mcs[-1] if mcs else "?"}（窗口内共 {len(has_l)} 条）'

p("=" * 88)
p("【验证 K】limit 过滤法 vs. 之前全量法 —— 结果必须完全一致")
p("=" * 88)
EXPECT = {
    ("carpet", "26.1"): "DEGRADED:OLD_VERSION_ONLY",
    ("carpet", "26.3"): "READY",
    ("journeymap", "26.3"): "READY",
    ("jei", "26.1"): "DEGRADED:OLD_VERSION_ONLY",
    ("jei", "26.3"): "DEGRADED:PRERELEASE_ONLY",
}
t0 = time.time()
allok = True
for (slug, mc), exp in EXPECT.items():
    got, why = evaluate(slug, mc, "fabric")
    ok = got == exp
    allok &= ok
    p(f"  {'OK ' if ok else 'MISMATCH'}  {slug:12s} {mc:5s} -> {got:28s} (期望 {exp})")
    p(f"          {why}")
p(f"\n  全部一致: {allok}")
p(f"  用掉 {REQ['n']} 个请求 / {REQ['bytes']/1024:.1f} KB / {time.time()-t0:.2f}s（{len(EXPECT)} 次判定）")
p(f"  外推 200 个模组: 约 {REQ['n']/len(EXPECT)*200:.0f} 个请求 / {REQ['bytes']/len(EXPECT)*200/1024/1024:.1f} MB")

p()
p("=" * 88)
p("【验证 L】过滤参数支持度")
p("=" * 88)
for label, params in [
    ("version_type=release 过滤", {"loaders": '["fabric"]', "version_type": "release", "limit": 3}),
    ("game_versions+loaders+limit", {"game_versions": '["26.1"]', "loaders": '["fabric"]', "limit": 3}),
]:
    d = get("/project/jei/version", params)
    p(f"  {label:30s} -> {len(d)} 条: " +
      ", ".join(f'{v["version_number"]}({v["version_type"]})' for v in d))

p()
p("  结论：version_type 参数", "被忽略（返回中仍混有 beta）" if any(v["version_type"] != "release" for v in get("/project/jei/version", {"loaders": '["fabric"]', "version_type": "release", "limit": 10})) else "有效")

open(r"D:\Programme\python_prgram\mod-version-checker\.probe_algo.txt", "w", encoding="utf-8").write("\n".join(out))
print("WROTE")
