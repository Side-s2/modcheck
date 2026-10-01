# -*- coding: utf-8 -*-
import json, urllib.parse, urllib.request, urllib.error, time
UA = {"User-Agent": "modcheck-feasibility/0.1"}
BASE = "https://api.modrinth.com/v2"
out = []
def p(*s): out.append(" ".join(str(x) for x in s))

def get(path, params=None):
    url = BASE + path + (("?" + urllib.parse.urlencode(params)) if params else "")
    t0 = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
            body = r.read()
            return len(body), json.loads(body), time.time() - t0, dict(r.headers)
    except urllib.error.HTTPError as e:
        return len(e.read()), None, time.time() - t0, dict(e.headers)

p("=" * 82)
p("【验证 I】版本端点是否支持 limit / 过滤，以及各取数方式的体积")
p("=" * 82)

P = '[["fabric"]]'
tests = [
    ("全量", "/project/jei/version", None),
    ("按加载器过滤", "/project/jei/version", {"loaders": '["fabric"]'}),
    ("按加载器+游戏版本过滤", "/project/jei/version", {"game_versions": '["26.1"]', "loaders": '["fabric"]'}),
    ("limit=1", "/project/jei/version", {"limit": 1}),
    ("按加载器 + limit=1", "/project/jei/version", {"loaders": '["fabric"]', "limit": 1}),
    ("offset=0&limit=5", "/project/jei/version", {"offset": 0, "limit": 5}),
]
for label, path, params in tests:
    size, data, dt, hdrs = get(path, params)
    n = len(data) if isinstance(data, list) else "ERR"
    p(f"  {label:26s} HTTP体积={size/1024:9.1f} KB  条目数={str(n):6s}  耗时={dt:5.2f}s")

p()
p("=" * 82)
p("【验证 J】关键问题：能否用少量请求判定「该加载器的最新版是否支持目标 MC」")
p("=" * 82)

# 方案：先取 /project/{slug}（含 versions[] 版本ID列表，看是否为倒序）
for slug in ["carpet", "journeymap", "jei"]:
    size, proj, dt, _ = get(f"/project/{slug}")
    vids = proj.get("versions", [])
    p(f"\n  {slug}: /project 体积={size/1024:.1f} KB, versions[] 长度={len(vids)}, 前3个id={vids[:3]}")

# 取 carpet 的 versions[] 前几个，逐个 /version/{id} 看是否倒序且体积小
size, proj, _, _ = get("/project/carpet")
p()
p("  carpet 的 versions[] 前 6 个（逐个 /version/{id} 查询）:")
for vid in proj["versions"][:6]:
    s2, v, _, _ = get(f"/version/{vid}")
    p(f"    {vid:12s} 单体体积={s2:6d} B  version_number={v['version_number']:12s} type={v['version_type']:8s} "
      f"loaders={v['loaders']} gv={v['game_versions'][:2]} date={v['date_published'][:10]}")

p()
p("  journeymap 的 versions[] 前 8 个（验证多加载器交错情况）:")
size, proj, _, _ = get("/project/journeymap")
for vid in proj["versions"][:8]:
    s2, v, _, _ = get(f"/version/{vid}")
    p(f"    version_number={v['version_number']:24s} loaders={str(v['loaders']):22s} gv={str(v['game_versions'][:2]):18s} date={v['date_published'][:10]}")
p(f"    /project/journeymap 体积={size/1024:.1f} KB")

open(r"D:\Programme\python_prgram\mod-version-checker\.probe_limit.txt", "w", encoding="utf-8").write("\n".join(out))
print("WROTE")
