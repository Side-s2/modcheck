# -*- coding: utf-8 -*-
"""下载一套真实模组 jar，构成"服主升级前夜"的验收数据集。

用法:
    .toolchain\Python311\python.exe docs\research\09_fetch_demo_mods.py

产物: .demo_mods/  （已 gitignore，约 10 MB）
特点: 部分文件以 PCL 格式命名（带 [中文名]），用于验证"重命名后仍能靠 sha1 精确识别"。
"""
import json, os, urllib.parse, urllib.request, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".demo_mods"
UA = {"User-Agent": "modcheck-demo/0.1"}
BASE = "https://api.modrinth.com/v2"

# (保存文件名, slug, 加载器, 目标 MC, 备注)
PLAN = [
    ("[地毯] fabric-carpet-26.1+v260402.jar",        "carpet",     "fabric", "26.1", "PCL 格式 + 真实 jar"),
    ("[旅程地图] journeymap-26.1-fabric.jar",        "journeymap", "fabric", "26.1", "PCL 格式 + 多加载器陷阱样本"),
    ("jei-26.1-fabric.jar",                          "jei",        "fabric", "26.1", "仅测试版样本"),
    ("lithium-fabric.jar",                           "lithium",    "fabric", "26.1", "通用格式"),
    ("fabric-api-26.1.jar",                          "fabric-api", "fabric", "26.1", "前置库"),
    ("create-1.20.1-forge.jar",                      "create",     "forge",  "1.20.1", "只有 Forge/NeoForge，Fabric 下必然阻塞"),
]

def get(path, **params):
    url = BASE + path + (("?" + urllib.parse.urlencode(params)) if params else "")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))

def download(url, dest: Path) -> int:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r, open(dest, "wb") as f:
        while True:
            c = r.read(1 << 16)
            if not c: break
            f.write(c)
    return dest.stat().st_size

def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for fname, slug, loader, mc, note in PLAN:
        dest = OUT / fname
        try:
            versions = get(f"/project/{slug}/version",
                           game_versions=json.dumps([mc]), loaders=json.dumps([loader]),
                           version_type="release", limit=5)
            if not versions:
                versions = get(f"/project/{slug}/version", loaders=json.dumps([loader]), limit=1)
            if not versions:
                print(f"[SKIP] {slug}: 没有 {loader} 版本"); continue
            v = versions[0]
            f = next((x for x in v["files"] if x.get("primary")), v["files"][0])
            if dest.exists() and dest.stat().st_size == f["size"]:
                print(f"[KEEP] {fname}"); manifest.append((fname, slug, v["version_number"], f["hashes"]["sha1"])); continue
            size = download(f["url"], dest)
            with zipfile.ZipFile(dest) as z:
                has_meta = any(n in z.namelist() for n in
                               ("fabric.mod.json", "quilt.mod.json", "META-INF/mods.toml", "META-INF/neoforge.mods.toml"))
            print(f"[OK]   {fname:46s} {size/1024:8.0f} KB  {slug}@{v['version_number']}  元数据={has_meta}")
            manifest.append((fname, slug, v["version_number"], f["hashes"]["sha1"]))
        except Exception as e:
            print(f"[FAIL] {fname}: {type(e).__name__}: {e}")

    # 合成边界样本
    (OUT / "broken-mod.jar").write_bytes(b"this is not a zip file at all\n" * 40)
    print("[OK]   broken-mod.jar                              （损坏 jar，验证容错）")
    (OUT / "README.txt").write_text("这不是模组文件，验证扫描时的忽略逻辑\n", encoding="utf-8")
    print("[OK]   README.txt                                 （非 jar，应被忽略）")
    sub = OUT / "nested"
    sub.mkdir(exist_ok=True)
    (sub / "should-be-ignored.jar").write_bytes(b"PK\x05\x06" + b"\x00" * 18)
    print("[OK]   nested/should-be-ignored.jar              （子目录，验证是否递归）")

    (OUT / "_manifest.json").write_text(
        json.dumps([{"file": a, "slug": b, "version": c, "sha1": d} for a, b, c, d in manifest],
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n共 {len(list(OUT.glob('*.jar')))} 个 jar 写入 {OUT}")
    return 0

raise SystemExit(main())
