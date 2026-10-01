# -*- coding: utf-8 -*-
"""主 Agent 集成验证：真实 Modrinth 数据 → 真实 Provider 解析 → 真实 classify 判定。
并与 docs/research/results/10_ground_truth.json（独立实现算出的基准）逐条比对。

同时统计每模组的真实请求数与下载字节数（验收 PRD §1.3 的 S13）。
"""
import json, sys, tempfile
from pathlib import Path

ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))

from modcheck.cache import HttpCache
from modcheck.core.checker import classify
from modcheck.core.models import Loader
from modcheck.providers.http import HttpClient, HttpConfig
from modcheck.providers.modrinth import ModrinthProvider

GT = json.loads((ROOT / "docs/research/results/10_ground_truth.json").read_text(encoding="utf-8"))

tmp = Path(tempfile.mkdtemp(prefix="mvc-live-"))
cfg = HttpConfig()
client = HttpClient(cfg, cache=HttpCache(tmp))
prov = ModrinthProvider(client)

# 记录每个 URL 的下载体积（直接量 transport 层）
import modcheck.providers.http as httpmod
sizes = {}
real_transport = client._transport
def measuring(method, url, headers, data, timeout):
    resp = real_transport(method, url, headers, data, timeout)
    sizes[url] = len(resp.body or b"")
    return resp
client._transport = measuring

CASES = [
    ("carpet", "26.3", "fabric"), ("carpet", "26.1", "fabric"),
    ("journeymap", "26.3", "fabric"), ("jei", "26.1", "fabric"),
    ("jei", "26.3", "fabric"), ("create", "26.3", "fabric"),
]

print("=" * 104)
print("真实数据端到端（Provider → classify）与独立基准比对")
print("=" * 104)
allok = True
for slug, mc, lname in CASES:
    loader = Loader(lname)
    sizes.clear(); client.reset_stats()
    try:
        a = prov.releases_for_loader(slug, loader)
        b = prov.compat_releases(slug, mc, loader)
        b2 = prov.compat_any(slug, mc, loader) if not b else []
        project = prov.get_project(slug)
        vcount = project.version_count if project is not None else None
        c = classify(loader=loader, mc_version=mc,
                     releases_for_loader=a, compat_releases=b, compat_any=b2,
                     version_count=vcount)
    except Exception as e:
        print(f"  {slug:12s} {mc:5s}/{lname:9s}  !! {type(e).__name__}: {e}")
        allok = False
        continue
    reqs, hits = client.stats
    total = sum(sizes.values())
    exp = GT["cases"].get(f"{mc}/{lname}", {}).get(slug, {})
    want = (exp.get("status"), exp.get("reason"))
    got = (c.status.name, c.reason.value)
    ok = (want == (None, None)) or (got == want)
    allok &= ok
    print(f"  {'OK  ' if ok else 'FAIL'} {slug:12s} {mc:5s}/{lname:9s} -> {got[0]:8s}/{got[1]:18s}"
          f" 请求={reqs} 缓存={hits} 下载={total/1024:6.1f} KB" + ("" if ok else f"   基准={want}"))
    if not ok:
        print(f"         实际明细: latest={getattr(c.latest_for_loader,'version_number',None)} "
              f"compat={getattr(c.latest_compat,'version_number',None)} "
              f"any={getattr(c.latest_any,'version_number',None)} max_mc={c.max_supported_mc}")

print()
print("=" * 104)
print("S13 成本核算（每模组请求数与下载体积）")
print("=" * 104)
sizes.clear(); client.reset_stats(); client._cache = None     # 关缓存，量最坏情况
worst = 0
for slug, mc, lname in [("jei", "26.3", "fabric"), ("journeymap", "26.3", "fabric"), ("carpet", "26.3", "fabric")]:
    sizes.clear(); client.reset_stats()
    loader = Loader(lname)
    prov.releases_for_loader(slug, loader)
    b = prov.compat_releases(slug, mc, loader)
    if not b:
        prov.compat_any(slug, mc, loader)
    reqs, _ = client.stats
    total = sum(sizes.values())
    worst = max(worst, reqs)
    print(f"  {slug:12s} {mc}/{lname}: 请求 {reqs} 个，下载 {total/1024:.1f} KB"
          + ("   ✅ 在 S13 预算内（≤3 请求 / ≤5 KB）" if reqs <= 3 and total <= 5120 else "   ⚠️ 超预算"))

print()
print("=" * 104)
print("按 30 模组（mods_sample 规模）外推首次检查成本")
print("=" * 104)
sizes.clear(); client.reset_stats(); client._cache = None
agg_req = agg_bytes = 0
for slug, mc, lname in CASES:
    sizes.clear(); client.reset_stats()
    loader = Loader(lname)
    prov.releases_for_loader(slug, loader)
    if not prov.compat_releases(slug, mc, loader):
        prov.compat_any(slug, mc, loader)
    r_, _ = client.stats
    agg_req += r_; agg_bytes += sum(sizes.values())
per_req = agg_bytes / max(agg_req, 1)
print(f"  实测 6 个模组: 请求 {agg_req} 个, 下载 {agg_bytes/1024:.1f} KB (平均 {per_req/1024:.1f} KB/请求)")
print(f"  外推 200 个模组: 约 {agg_req/6*200:.0f} 个请求, 约 {agg_bytes/6*200/1024/1024:.1f} MB")
print(f"  PRD S13 当前写的预算是「≤3 请求 / ≤5 KB 每模组」→ 实测每模组 {agg_bytes/6/1024:.1f} KB，**预算与现实不符**")

print()
print("全部与基准一致" if allok else "存在与基准不一致的条目")
import shutil; shutil.rmtree(tmp, ignore_errors=True)
raise SystemExit(0 if allok else 1)
