"""现场生成演示环境（PM 验收用）——**不提交任何二进制文件**。

用法：
    .toolchain\\Python311\\python.exe tests\\make_fixtures.py
生成：
    tests/_fixtures/mods_demo/            6+1 个 jar（含损坏 jar、禁用文件、非模组 jar）
    tests/_fixtures/profiles/demo.json    一份演示清单
"""
from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "_fixtures"

#: 演示清单里的模组（carpet/lithium/fabric-api 能在本地 jar 里找到，其余用于演示各条分支）
DEMO_MODS = [
    ("carpet", "Carpet", "地毯", "carpet", "[地毯] fabric-carpet-26.1+v260402.jar", "26.1"),
    ("lithium", "Lithium", "锂", "lithium", "lithium-fabric-0.12.1.jar", "0.12.1"),
    ("fabric-api", "Fabric API", "Fabric API", "fabric-api", "fabric-api-0.92.2+1.20.1.jar", "0.92.2+1.20.1"),
    ("jei", "Just Enough Items", "JEI", "jei", "jei-26.1-fabric.jar", "29.34.0.90"),
    ("create", "Create", "创造", "create", "create-1.20.1-forge.jar", "6.0.8"),
    ("create-fabric", "Create Fabric", "机械动力F", "create-fabric", "create-fabric.jar", "6.0.8.1"),
    ("journeymap", "JourneyMap", "旅程地图", "journeymap", "journeymap-26.1-fabric.jar", "5.9.18"),
    ("no-such-mod-xyz", "No Such Mod", None, "no-such-mod-xyz", "no-such-mod-xyz.jar", None),
]


def _write_jar(path: Path, members: dict[str, str]) -> None:
    """写一个最小可解析的 jar。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, text in members.items():
            zf.writestr(name, text)


def _fabric(mod_id: str, name: str, version: str, mc: str | None = None) -> str:
    """构造 fabric.mod.json 的内容。"""
    payload: dict[str, object] = {"id": mod_id, "name": name, "version": version,
                                  "schemaVersion": 1}
    if mc:
        payload["depends"] = {"minecraft": mc}
    return json.dumps(payload, ensure_ascii=False)


def make_mods_dir(root: Path | None = None) -> Path:
    """生成演示 mods 文件夹，返回目录路径。"""
    target = Path(root) if root is not None else FIXTURES / "mods_demo"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    _write_jar(target / "[\u5730\u6bef] fabric-carpet-26.1+v260402.jar",
               {"fabric.mod.json": _fabric("carpet", "Carpet Mod", "26.1+v260402", ">=26.1")})
    _write_jar(target / "lithium-fabric-0.12.1.jar",
               {"fabric.mod.json": _fabric("lithium", "Lithium", "0.12.1")})
    _write_jar(target / "fabric-api-0.92.2+1.20.1.jar",
               {"fabric.mod.json": _fabric("fabric-api", "Fabric API", "0.92.2+1.20.1", ">=1.20.1")})
    # 同一 modid 的第二个文件 -> 触发"多个版本文件"告警
    _write_jar(target / "fabric-carpet-26.3+v260915.jar",
               {"fabric.mod.json": _fabric("carpet", "Carpet Mod", "26.3+v260915", ">=26.3")})
    # 结构正常但没有模组元数据 -> 应被跳过
    _write_jar(target / "server-extra.jar", {"data/readme.txt": "not a mod"})
    # 损坏 jar -> 应被跳过且不崩
    (target / "broken.jar").write_bytes(b"x" * 100)
    # 已禁用文件 -> 应被跳过
    shutil.copyfile(target / "[\u5730\u6bef] fabric-carpet-26.1+v260402.jar",
                    target / "old-mod.jar.disabled")
    # 非 jar 文件 -> 应被跳过
    (target / "README.txt").write_text("这不是模组\n", encoding="utf-8")
    # 子文件夹 -> 不递归，只提示
    (target / "1.20.1-backup").mkdir()
    return target


def make_demo_profile(root: Path | None = None) -> Path:
    """生成演示清单 demo.json。"""
    directory = Path(root) if root is not None else FIXTURES / "profiles"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "demo.json"
    stamp = "2026-10-01T12:00:00+08:00"
    mods = []
    for key, display, cn_name, mod_id, file_name, current in DEMO_MODS:
        mods.append({
            "key": key, "display_name": display, "cn_name": cn_name, "mod_id": mod_id,
            "file_name": file_name, "sha1": None, "aliases": [],
            "sources": {"modrinth": None if key == "no-such-mod-xyz" else key,
                        "curseforge": None},
            "detected": {"mc_versions": [], "loaders": [], "mod_version": None},
            "match_status": "exact" if key != "no-such-mod-xyz" else "unmatched",
            "source_kind": None, "current_version": current, "notes": "",
            "added_at": stamp, "updated_at": stamp,
        })
    payload = {"schema_version": 1, "name": "demo", "description": "PM 验收演示清单",
               "created_at": stamp, "updated_at": stamp, "mods": mods}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    """生成全部演示文件。"""
    mods = make_mods_dir()
    profile = make_demo_profile()
    print("mods:", mods)
    print("profile:", profile)
    return 0


if __name__ == "__main__":
    sys.exit(main())
