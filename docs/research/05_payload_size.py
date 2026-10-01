# -*- coding: utf-8 -*-
import json, urllib.request
UA = {"User-Agent": "modcheck-feasibility/0.1"}
BASE = "https://api.modrinth.com/v2"
out = []
def p(*s): out.append(" ".join(str(x) for x in s))

def get_raw(path):
    with urllib.request.urlopen(urllib.request.Request(BASE + path, headers=UA), timeout=30) as r:
        return r.read()

p("=" * 76)
p("【验证 G】响应体积实测（决定缓存策略）")
p("=" * 76)
total_v = total_b = 0
for slug in ["carpet", "jei", "sodium", "lithium", "ferrite-core", "journeymap"]:
    b = get_raw(f"/project/{slug}/version")
    n = len(json.loads(b))
    p(f"  {slug:14s} 版本数={n:5d}  /version 响应={len(b)/1024:8.1f} KB  平均/条={len(b)/max(n,1):6.0f} B")
    total_v += n; total_b += len(b)
p(f"  合计 {total_v} 个版本 / {total_b/1024:.0f} KB → 单个模组平均 {total_b/6/1024:.0f} KB")
p(f"  外推 200 个模组：约 {total_b/6*200/1024/1024:.1f} MB 原始 JSON")
p()
p("  精简后（只保留 version_number/date/type/game_versions/loaders/hashes）体积对比：")
b = get_raw("/project/carpet/version")
data = json.loads(b)
slim = [{"v": v["version_number"], "d": v["date_published"], "t": v["version_type"],
         "g": v["game_versions"], "l": v["loaders"]} for v in data]
p(f"    原始 {len(b)/1024:.1f} KB → 精简 {len(json.dumps(slim, ensure_ascii=False).encode())/1024:.1f} KB"
  f"（压缩到 {len(json.dumps(slim, ensure_ascii=False).encode())/len(b)*100:.0f}%）")

p()
p("=" * 76)
p("【验证 H】/project/{slug} 轻量预筛可行性")
p("=" * 76)
proj = json.loads(get_raw("/project/carpet"))
p(f"  /project/carpet 响应={len(get_raw('/project/carpet'))/1024:.1f} KB")
p(f"  game_versions 全部={proj['game_versions']}")
p(f"  loaders={proj['loaders']}")
p(f"  server_side={proj['server_side']!r}")
p()
p("  用途：先用 /project 做一次轻量预筛——若目标 MC 不在 game_versions 里，")
p("       直接判 🔴 无需再拉 134 条版本；只在有可能兼容时才拉 /version。")

open(r"D:\Programme\python_prgram\mod-version-checker\.probe_size.txt", "w", encoding="utf-8").write("\n".join(out))
print("WROTE")
