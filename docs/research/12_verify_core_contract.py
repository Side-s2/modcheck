# -*- coding: utf-8 -*-
"""主 Agent 独立验证脚本：直接调用 modcheck.core 的公开接口，用真实数据检验契约。

不依赖程序员自己的测试，属于交叉验证。
运行：.toolchain\Python311\python.exe docs\research\12_verify_core_contract.py
"""
import json, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

FILENAMES = [
    "[地毯] fabric-carpet-26.1+v260402.jar", "fabric-api-0.92.2+1.20.1.jar",
    "lithium-fabric-0.12.1.jar", "ferritecore-6.0.1-fabric.jar",
    "journeymap-1.20.1-5.9.18-fabric.jar", "chunky-fabric-1.3.146.jar",
    "spark-1.10.53-fabric.jar", "cloth-config-11.1.106-fabric.jar",
    "modernfix-fabric-5.19.4+mc1.20.1.jar", "sodium-fabric-0.5.8+mc1.20.1.jar",
    "jei-1.20.1-fabric-15.2.0.27.jar", "servercore-fabric-1.4.6+1.20.1.jar",
    "c2me-fabric-mc1.20.1-0.2.0+alpha.11.50.jar", "fabric-carpet-26.3+v260901.jar",
    "torchmaster-fabric-1.20.1-2.8.0.jar", "searchlight-fabric-1.20.1-1.0.0.jar",
    "prefab-1.20.1-1.0.0.jar", "architectury-fabric-1.20.1-9.0.0.jar",
]


def known_mc() -> list[str]:
    req = urllib.request.Request("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json",
                                 headers={"User-Agent": "modcheck-verify/0.1"})
    man = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    return [v["id"] for v in man["versions"] if v["type"] == "release"]


def main() -> int:
    from modcheck.core.filename import parse_jar_filename
    from modcheck.core.jarmeta import read_jar_meta
    known = known_mc()
    print(f"官方正式版 {len(known)} 条\n")

    print("=== filename.parse_jar_filename（无 known 锚点）===")
    for f in FILENAMES[:6]:
        try:
            p = parse_jar_filename(f)
            print(f"  OK   {f:46s} name={p.name!r}")
        except Exception as e:
            print(f"  FAIL {f:46s} {type(e).__name__}: {e}")

    print("\n=== filename.parse_jar_filename（有 known 锚点）===")
    for f in FILENAMES:
        p = parse_jar_filename(f, known_mc_versions=known)
        print(f"  {f:46s} name={str(p.name):16s} cand={p.name_candidates} mc={p.mc_version} ver={p.mod_version}")

    print("\n=== jarmeta.read_jar_meta（真实 jar）===")
    ok = sum(1 for p in sorted((ROOT / "mods_sample").glob("*.jar")) if read_jar_meta(p).mod_id)
    total = len(list((ROOT / "mods_sample").glob("*.jar")))
    print(f"  读到 modid: {ok}/{total}")
    print(f"  损坏 jar 容错: {read_jar_meta(ROOT / '.demo_mods' / 'broken-mod.jar').error}")
    return 0


raise SystemExit(main())
