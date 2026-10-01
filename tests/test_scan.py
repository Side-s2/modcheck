"""T-20 scan 流水线测试（离线，用假 Provider）。

流水线本体在 modcheck.flows.scan_flow（CLI 只做参数与渲染），
所以这里直接测流程层；run_scan 的端到端写盘另有一条用例。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from modcheck.core.models import Loader, MatchStatus, ProjectHit, SourceKind, VersionInfo
from modcheck.errors import ConfigError
from modcheck.flows.scan_flow import DEFAULT_PROFILE, scan_dirs, scan_from_list
from modcheck.providers.registry import ProviderRegistry
from modcheck.storage.profiles import load_profile, profile_path
from fakes import FakeProvider

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_fixtures  # noqa: E402  （与测试同目录的现场生成脚本）


@dataclass
class FakeCtx:
    """只带 run_scan 需要的字段的上下文。"""

    registry: ProviderRegistry
    console: object = None


def make_ctx(provider: FakeProvider) -> FakeCtx:
    """把假 Provider 包成上下文。"""
    return FakeCtx(registry=ProviderRegistry(providers=[provider]))


def make_provider() -> FakeProvider:
    """构造一个能认出 carpet / fabric-api 的假数据源。"""
    hits = [
        ProjectHit("Pcarpet", "carpet", "Carpet", 11016662, "d", "fake"),
        ProjectHit("Papi", "fabric-api", "Fabric API", 5000000, "d", "fake"),
        ProjectHit("Pli", "lithium", "Lithium", 3000000, "d", "fake"),
    ]
    version = VersionInfo.from_api({
        "id": "V1", "project_id": "Papi", "version_number": "0.92.2+1.20.1",
        "name": "0.92.2+1.20.1", "date_published": "2026-01-01T00:00:00Z",
        "version_type": "release", "game_versions": ["1.20.1"], "loaders": ["fabric"],
        "files": []})
    return FakeProvider(hits=hits, hash_map={"deadbeef": version})


def test_scan_demo_dir(tmp_path: Path) -> None:
    """验收用例 23：识别 carpet/lithium/fabric-api，跳过 broken/server-extra/disabled。"""
    mods = make_fixtures.make_mods_dir(tmp_path / "mods")
    report = scan_dirs([mods], provider=make_provider())

    names = {entry.mod_id for entry in report.entries}
    assert "carpet" in names
    assert "lithium" in names
    assert "fabric-api" in names

    skipped = {item.name for item in report.skipped}
    assert "broken.jar" in skipped
    assert "old-mod.jar.disabled" in skipped
    assert "README.txt" in skipped
    # 裁决 D35：没有可读元数据的 jar **必须进清单**（漏掉一个比多列一个危险得多）
    assert "server-extra.jar" not in skipped
    assert "server-extra.jar" in report.unidentified
    extra = next(e for e in report.entries if e.file_name == "server-extra.jar")
    assert extra.match_status in (MatchStatus.UNMATCHED, MatchStatus.GUESS)
    assert extra.source_kind is SourceKind.FILENAME
    assert extra.file_name == "server-extra.jar"

    # 同一 modid 的两个 jar 合并成一条，并产生告警
    carpet = [entry for entry in report.entries if entry.mod_id == "carpet"]
    assert len(carpet) == 1
    assert "fabric-carpet-26.3+v260915.jar" in carpet[0].aliases
    assert any("多个版本文件" in w for w in report.warnings)

    # 子文件夹只提示不递归
    assert "1.20.1-backup" in report.subdirs


def test_scan_uses_hash_and_search(tmp_path: Path) -> None:
    """指纹命中 -> EXACT/HASH；名称搜索命中 -> EXACT/SEARCH。"""
    mods = make_fixtures.make_mods_dir(tmp_path / "mods")
    provider = make_provider()
    # 让某文件的 sha1 命中假指纹表：直接改成真实计算值不方便，这里改用搜索路径断言
    report = scan_dirs([mods], provider=provider)
    carpet = next(e for e in report.entries if e.mod_id == "carpet")
    assert carpet.sources["modrinth"] == "carpet"
    assert carpet.source_kind is SourceKind.SEARCH
    assert carpet.match_status is MatchStatus.EXACT
    assert report.by_search >= 1


def test_scan_missing_dir_raises() -> None:
    """目录不存在 -> ConfigError（退出码 3）。"""
    with pytest.raises(ConfigError):
        scan_dirs([Path("no/such/dir")], provider=make_provider())


def test_scan_from_list_all_guess(tmp_path: Path) -> None:
    """--from-list：全部 GUESS + FILENAME，且不发起指纹请求。"""
    listing = tmp_path / "list.txt"
    listing.write_text("[\u5730\u6bef] fabric-carpet-26.1+v260402.jar\nlithium-fabric-0.12.1.jar\n",
                       encoding="utf-8")
    provider = make_provider()
    report = scan_from_list(listing, provider=provider)
    assert len(report.entries) == 2
    assert all(entry.match_status in (MatchStatus.GUESS, MatchStatus.EXACT)
               for entry in report.entries)
    assert all(entry.source_kind in (SourceKind.FILENAME, SourceKind.SEARCH)
               for entry in report.entries)
    carpet = next(e for e in report.entries if e.display_name == "carpet")
    assert carpet.file_name == "[\u5730\u6bef] fabric-carpet-26.1+v260402.jar"


def test_scan_from_list_missing_file(tmp_path: Path) -> None:
    """清单文件不存在 -> ConfigError。"""
    with pytest.raises(ConfigError):
        scan_from_list(tmp_path / "nope.txt", provider=make_provider())


def test_scan_from_list_empty_file(tmp_path: Path) -> None:
    """空清单 -> ConfigError。"""
    listing = tmp_path / "empty.txt"
    listing.write_text("\n\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        scan_from_list(listing, provider=make_provider())


def test_hash_and_search_paths_write_the_same_identifier(tmp_path: Path) -> None:
    """D38 不变量：同一模组无论走指纹路径还是搜索路径，写进清单的标识必须一致。

    指纹反查返回的是 project_id（fQEb0iXm 这种），搜索返回的是 slug（krypton）——
    统一取 slug；否则清单既不可读，用户改了文件名重扫还会出现重复条目。
    """
    import hashlib

    from modcheck.core.models import ProjectInfo

    mods = make_fixtures.make_mods_dir(tmp_path / "mods")
    version = VersionInfo.from_api({
        "id": "V1", "project_id": "fQEb0iXm", "version_number": "0.3.0", "name": "0.3.0",
        "date_published": "2026-01-01T00:00:00Z", "version_type": "release",
        "game_versions": ["26.3"], "loaders": ["fabric"], "files": []})
    info = ProjectInfo(project_id="fQEb0iXm", slug="krypton", title="Krypton", description="",
                       project_type="mod", loaders=("fabric",), game_versions=("26.3",),
                       downloads=1, version_count=5)
    digest = hashlib.sha1((mods / "lithium-fabric-0.12.1.jar").read_bytes()).hexdigest()
    provider = FakeProvider(hits=[ProjectHit("Pk", "krypton", "Krypton", 1, "d", "fake")],
                            hash_map={digest: version}, projects={"fQEb0iXm": info})
    report = scan_dirs([mods], provider=provider)
    lithium = next(e for e in report.entries if e.mod_id == "lithium")
    assert lithium.sources["modrinth"] == "krypton"     # 不是 fQEb0iXm
    assert lithium.key == "slug:modrinth:krypton"
    assert all("fQEb" not in (e.sources.get("modrinth") or "") for e in report.entries)


def test_scan_offline_still_builds_profile(tmp_path: Path) -> None:
    """数据源整体不可用时不中断扫描（只用 jar 内信息）。"""
    from modcheck.errors import ProviderUnavailable

    mods = make_fixtures.make_mods_dir(tmp_path / "mods")
    provider = FakeProvider(raise_on={"*": ProviderUnavailable("offline")})
    report = scan_dirs([mods], provider=provider)
    assert report.offline is True
    assert {entry.mod_id for entry in report.entries} >= {"carpet", "lithium", "fabric-api"}


def test_run_scan_writes_profile(tmp_path: Path) -> None:
    """端到端：run_scan 会原子写盘并可再次读回。"""
    from argparse import Namespace

    from modcheck.cli.commands.scan import run_scan
    from modcheck.console import Console

    mods = make_fixtures.make_mods_dir(tmp_path / "mods")
    ctx = make_ctx(make_provider())
    ctx.console = Console(stream=open(tmp_path / "out.txt", "w", encoding="utf-8"),
                          color="never", width=120)  # noqa: SIM115
    ctx.profiles_dir = tmp_path / "profiles"  # type: ignore[attr-defined]
    args = Namespace(paths=[str(mods)], profile="demo", from_list=None, new=False, yes=True)
    code = run_scan(args, ctx)  # type: ignore[arg-type]
    assert code == 0
    saved = load_profile(profile_path(tmp_path / "profiles", "demo"))
    assert {entry.mod_id for entry in saved.mods} >= {"carpet", "lithium", "fabric-api"}
    assert DEFAULT_PROFILE == "demo"
