
import json, urllib.request, urllib.parse
def get(u):
    req = urllib.request.Request(u, headers={"User-Agent":"modcheck-pm/0.1 (spec verification)"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)
for slug in ["create-fabric", "sodium", "lithium", "fabric-api"]:
    try:
        p = get(f"https://api.modrinth.com/v2/project/{slug}")
        vs = get(f"https://api.modrinth.com/v2/project/{slug}/version")
        lv = vs[0] if vs else None
        print(f'{slug}: title={p["title"]!r} loaders={p["loaders"]} projHas263={"26.3" in p["game_versions"]}')
        if lv:
            print(f'   latest: ver={lv["version_number"]!r} type={lv["version_type"]} gv={lv["game_versions"]} file={[f["filename"] for f in lv["files"]]}')
        rel263 = [v for v in vs if "26.3" in v["game_versions"] and "fabric" in v["loaders"]]
        print(f'   fabric+26.3 versions: {len(rel263)}')
        print(f'   file[0] keys: {sorted(lv["files"][0].keys()) if lv else None}')
    except Exception as e:
        print(slug, "ERR", getattr(e, "code", ""), type(e).__name__)
