# -*- coding: utf-8 -*-
import hashlib, io, json, urllib.parse, urllib.request, zipfile
UA = {"User-Agent": "modcheck-feasibility/0.1", "Content-Type": "application/json"}
BASE = "https://api.modrinth.com/v2"
out = []
def p(s=""): out.append(str(s))

def get(path):
    req = urllib.request.Request(BASE + path, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def post(path, payload):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode("utf-8"),
                                 headers=UA, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

def get_bytes(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
        return r.read()

p("=" * 88)
p("【验证 C】用 jar 的 sha1 精确反查项目与版本（POST /v2/version_files）")
p("=" * 88)

targets = [("carpet", "fabric"), ("jei", "fabric"), ("sodium", "fabric")]
hashes = {}
for slug, loader in targets:
    try:
        versions = get(f"/project/{slug}/version")
        cand = [v for v in versions if loader in v["loaders"] and v["files"]]
        v = cand[0]
        f = next((x for x in v["files"] if x.get("primary")), v["files"][0])
        blob = get_bytes(f["url"])
        sha1 = hashlib.sha1(blob).hexdigest()
        api_sha1 = f["hashes"].get("sha1")
        hashes[sha1] = (slug, v["version_number"], f["filename"])
        p(f"{slug:10s} {f['filename']:42s} 本地sha1={sha1[:16]}… API声明={str(api_sha1)[:16]}… 一致={sha1 == api_sha1}")
    except Exception as e:
        p(f"{slug}: 失败 {type(e).__name__}: {e}")

p()
p("批量反查（一次请求提交 %d 个 sha1）:" % len(hashes))
resp = post("/version_files", {"hashes": list(hashes), "algorithm": "sha1"})
for h, info in resp.items():
    expected = hashes.get(h)
    p(f"  返回 project_id={info['project_id']}  version_number={info['version_number']!r}  期望={expected}")
p(f"  返回条数={len(resp)} / 提交条数={len(hashes)}")

p()
p("不存在的哈希表现:")
fake = "0" * 40
r2 = post("/version_files", {"hashes": [fake], "algorithm": "sha1"})
p(f"  提交 1 个假哈希 -> 返回 {r2!r}")

p()
p("=" * 88)
p("【验证 D】只用 modid 搜索时的匹配质量")
p("=" * 88)
for term in ["fabric-api", "lithium", "ferritecore", "chunky", "spark", "cloth-config",
             "modernfix", "sodium", "servercore", "c2me", "carpet"]:
    data = get("/search?query=" + urllib.parse.quote(term) + "&limit=5&facets=" +
               urllib.parse.quote('[["project_type:mod"]]'))
    hits = data["hits"]
    import re as _re
    norm = lambda s: _re.sub(r"[-_. ]+", "", (s or "").lower())
    exact = [h["slug"] for h in hits if norm(h["slug"]) == norm(term) or norm(h["title"]) == norm(term)]
    p(f"  {term:14s} exact={str(exact):28s} top3={[h['slug'] for h in hits[:3]]}")

open(r"D:\Programme\python_prgram\mod-version-checker\.probe_hash_result.txt", "w", encoding="utf-8").write("\n".join(out))
print("WROTE", len(out), "lines")
