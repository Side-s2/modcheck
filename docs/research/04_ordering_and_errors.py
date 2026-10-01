# -*- coding: utf-8 -*-
import json, urllib.error, urllib.request
UA = {"User-Agent": "modcheck-feasibility/0.1"}
BASE = "https://api.modrinth.com/v2"
out = []
def p(*s): out.append(" ".join(str(x) for x in s))

def raw(path):
    req = urllib.request.Request(BASE + path, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")

p("=" * 80)
p("【验证 E】/project/{id}/version 是否真的按发布时间倒序")
p("=" * 80)
st, hdrs, body = raw("/project/carpet/version")
data = json.loads(body)
p(f"HTTP {st}, 条目数={len(data)}")
dates = [v["date_published"] for v in data]
p("前 8 条发布时间:", [d[:19] for d in dates[:8]])
p("是否严格倒序:", all(dates[i] >= dates[i+1] for i in range(len(dates)-1)))
p("是否严格升序:", all(dates[i] <= dates[i+1] for i in range(len(dates)-1)))
p()
p("前 5 条 version_number / loaders / game_versions / type:")
for v in data[:5]:
    p(f"   {v['version_number']:24s} loaders={v['loaders']} gv={v['game_versions'][:4]} type={v['version_type']} date={v['date_published'][:10]}")

p()
p("=" * 80)
p("【验证 F】错误处理与限流头")
p("=" * 80)
for path in ["/project/this-slug-definitely-does-not-exist-xyz", "/project/"]:
    st, h, b = raw(path)
    p(f"GET {path} -> HTTP {st}  body={b[:160]!r}")

st, h, b = raw("/project/carpet")
p()
p("限流相关响应头:")
for k in sorted(h):
    if k.lower() in ("x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset",
                     "ratelimit-limit", "ratelimit-remaining", "ratelimit-reset", "retry-after"):
        p(f"   {k}: {h[k]}")
p("   （若上面为空，说明 Modrinth 未在响应头暴露限流信息，文档口径为 300 req/min）")

p()
p("项目对象关键字段:")
proj = json.loads(b)
for k in ("id", "slug", "title", "project_type", "downloads", "game_versions", "loaders", "server_side", "client_side"):
    v = proj.get(k)
    p(f"   {k} = {str(v)[:120]}")
p(f"   全部顶层字段 = {sorted(proj.keys())}")

open(r"D:\Programme\python_prgram\mod-version-checker\.probe_order.txt", "w", encoding="utf-8").write("\n".join(out))
print("WROTE", len(out))
