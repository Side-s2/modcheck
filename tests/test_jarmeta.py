"""T-07 jar 元数据与指纹测试：第一优先识别手段，且永不抛异常。"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from modcheck.core.hashid import is_probably_jar, sha1_of_file
from modcheck.core.jarmeta import (MAX_MEMBER_BYTES, left_bound, parse_fabric_json,
                                   parse_mods_toml, read_jar_meta)


def _make_jar(path: Path, members: dict[str, bytes]) -> Path:
    """现场生成一个 jar（测试里不提交任何二进制）。"""
    with zipfile.ZipFile(path, "w") as zf:
        for name, raw in members.items():
            zf.writestr(name, raw)
    return path


def test_fabric_meta(tmp_path: Path) -> None:
    """fabric.mod.json：拿到 id / name / version，mc_hint 来自 depends.minecraft。"""
    raw = json.dumps({"id": "carpet", "name": "Carpet Mod", "version": "26.1+v260402",
                      "depends": {"minecraft": ">=26.1", "fabricloader": ">=0.15"}})
    jar = _make_jar(tmp_path / "[\u5730\u6bef] fabric-carpet-26.1+v260402.jar",
                    {"fabric.mod.json": raw.encode("utf-8")})
    meta = read_jar_meta(jar)
    assert meta.error is None
    assert (meta.mod_id, meta.name, meta.version) == ("carpet", "Carpet Mod", "26.1+v260402")
    assert meta.mc_hint == "26.1"
    assert meta.loader_hint == "fabric"
    assert meta.depends["fabricloader"] == [">=0.15"]
    assert meta.has_meta is True


def test_fabric_missing_minecraft_depend(tmp_path: Path) -> None:
    """实测：Fabric 模组不一定声明 depends.minecraft（jei 就是 None）。"""
    raw = json.dumps({"id": "jei", "name": "Just Enough Items", "version": "31.8.0.49"})
    jar = _make_jar(tmp_path / "jei.jar", {"fabric.mod.json": raw.encode("utf-8")})
    meta = read_jar_meta(jar)
    assert meta.mod_id == "jei"
    assert meta.mc_hint is None


def test_quilt_meta(tmp_path: Path) -> None:
    """quilt.mod.json 走同一条 JSON 解析路径，loader_hint=quilt。"""
    raw = json.dumps({"id": "qmod", "name": {"en_us": "Quilt Mod"}, "version": "1.0"})
    jar = _make_jar(tmp_path / "q.jar", {"quilt.mod.json": raw.encode("utf-8")})
    meta = read_jar_meta(jar)
    assert meta.mod_id == "qmod"
    assert meta.name == "Quilt Mod"
    assert meta.loader_hint == "quilt"


def test_neoforge_toml(tmp_path: Path) -> None:
    """neoforge.mods.toml：modId/displayName/version + dependencies 的左界。"""
    raw = b"""
modLoader="javafml"
loaderVersion="[4,)"
[[mods]]
modId="jei"
displayName="Just Enough Items"
version="31.8.0.49"
[[dependencies.jei]]
modId="minecraft"
versionRange="[26.3,26.4)"
"""
    jar = _make_jar(tmp_path / "jei-neoforge.jar", {"META-INF/neoforge.mods.toml": raw})
    meta = read_jar_meta(jar)
    assert (meta.mod_id, meta.name, meta.version) == ("jei", "Just Enough Items", "31.8.0.49")
    assert meta.loader_hint == "neoforge"
    assert meta.mc_hint == "26.3"
    assert meta.source_member == "META-INF/neoforge.mods.toml"


def test_forge_toml(tmp_path: Path) -> None:
    """旧版 Forge 用 META-INF/mods.toml。"""
    raw = b"""
[[mods]]
modId="create"
displayName="Create"
version="6.0.8"
[[dependencies.create]]
modId="minecraft"
versionRange="[1.20.1,1.21)"
"""
    jar = _make_jar(tmp_path / "create.jar", {"META-INF/mods.toml": raw})
    meta = read_jar_meta(jar)
    assert meta.mod_id == "create"
    assert meta.loader_hint == "forge"
    assert meta.mc_hint == "1.20.1"


def test_manifest_fallback(tmp_path: Path) -> None:
    """只有 MANIFEST.MF 时用 Implementation-Title 兜底。"""
    raw = b"Manifest-Version: 1.0\r\nImplementation-Title: Some Library\r\nImplementation-Version: 2.1\r\n"
    jar = _make_jar(tmp_path / "lib.jar", {"META-INF/MANIFEST.MF": raw})
    meta = read_jar_meta(jar)
    assert meta.name == "Some Library"
    assert meta.version == "2.1"
    assert meta.mod_id is None


def test_no_metadata_zip(tmp_path: Path) -> None:
    """结构正常但没有模组元数据：字段全 None，error 写明原因。"""
    jar = _make_jar(tmp_path / "server-extra.jar", {"data/x.txt": b"hello"})
    meta = read_jar_meta(jar)
    assert meta.mod_id is None
    assert meta.name is None
    assert meta.source_member is None
    assert meta.error is not None


def test_broken_jar_does_not_raise(tmp_path: Path) -> None:
    """100 字节垃圾：返回 error 且绝不抛异常。"""
    broken = tmp_path / "broken.jar"
    broken.write_bytes(b"x" * 100)
    meta = read_jar_meta(broken)
    assert meta.error is not None
    assert meta.mod_id is None
    assert meta.has_meta is False


def test_missing_file(tmp_path: Path) -> None:
    """文件不存在也不抛。"""
    meta = read_jar_meta(tmp_path / "nope.jar")
    assert meta.error is not None


def test_oversized_member_ignored(tmp_path: Path) -> None:
    """超大元数据条目直接放弃，不整包读进内存。"""
    big = b" " * (MAX_MEMBER_BYTES + 10)
    jar = _make_jar(tmp_path / "big.jar", {"fabric.mod.json": big})
    meta = read_jar_meta(jar)
    assert meta.error is not None
    assert meta.mod_id is None


def test_left_bound() -> None:
    """版本范围取左界；解析不出来返回 None（不猜）。"""
    assert left_bound("[1.20.1,1.21)") == "1.20.1"
    assert left_bound(">=26.3") == "26.3"
    assert left_bound("(,1.21]") is None
    assert left_bound("*") is None
    assert left_bound("") is None


def test_parse_helpers_on_bad_input() -> None:
    """坏 JSON / 坏 TOML 只返回 error，不抛。"""
    _, _, _, _, error = parse_fabric_json(b"{not json")
    assert error is not None
    _, _, _, _, error2 = parse_mods_toml(b"[[mods]")
    assert error2 is not None


def test_sha1_of_file_is_stable(tmp_path: Path) -> None:
    """sha1 两次一致，且等于标准库期望值。"""
    target = tmp_path / "a.bin"
    target.write_bytes(b"hello world")
    expected = hashlib.sha1(b"hello world").hexdigest()
    assert sha1_of_file(target) == expected
    assert sha1_of_file(target, chunk=3) == expected


def test_is_probably_jar(tmp_path: Path) -> None:
    """扩展名 + PK 魔数双条件。"""
    good = _make_jar(tmp_path / "good.jar", {"a.txt": b"x"})
    assert is_probably_jar(good) is True
    fake = tmp_path / "fake.jar"
    fake.write_bytes(b"not a zip at all")
    assert is_probably_jar(fake) is False
    plain = tmp_path / "plain.txt"
    plain.write_bytes(b"PK")
    assert is_probably_jar(plain) is False
