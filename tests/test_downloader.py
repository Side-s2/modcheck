"""R3-B02：core/downloader.py 的选品与文件名（离线，不联网）。"""
from __future__ import annotations

from pathlib import Path

from modcheck.core.downloader import (DOWNLOADABLE, DownloadPlan, MAX_FILENAME, conflicts,
                                      extra_files_count, fallback_filename, overwrite_key,
                                      part_path, pick_file, pick_version, plan_for, safe_filename)
from modcheck.core.models import FileInfo, Loader, ModEntry, ReasonCode, Status, VersionInfo
from modcheck.core.report import Report, ReportItem

OLD = "2000-01-01T00:00:00+08:00"


def file_info(name: str, *, primary: bool = False, size: int = 100) -> FileInfo:
    """造一个文件条目。"""
    return FileInfo(filename=name, url="https://cdn.example/" + name, primary=primary,
                    size=size, hashes={"sha1": "0" * 40})


def version(number: str = "1.0", *, files: tuple[FileInfo, ...] = (),
            channel: str = "release") -> VersionInfo:
    """造一个版本条目。"""
    return VersionInfo(version_id="V-" + number, version_number=number, name=number,
                       project_id="proj", date_published="2026-09-18T00:00:00Z",
                       version_type=channel, game_versions=("26.3",), loaders=("fabric",),
                       files=files)


def entry(key: str = "carpet", *, name: str = "", slug: str | None = None) -> ModEntry:
    """造一条清单记录。"""
    item = ModEntry(key=key, display_name=name or key, mod_id=key, updated_at=OLD)
    if slug:
        item.sources = {"modrinth": slug}
    return item


def report_item(mod: ModEntry, status: Status, *, latest: VersionInfo | None = None,
                compat: VersionInfo | None = None) -> ReportItem:
    """造一条报告条目。"""
    return ReportItem(mod=mod, status=status, reason=ReasonCode.OK, reason_key="reason.ok",
                      hint_key="advice.ok", latest_for_loader=latest, latest_compat=compat)


def make_report(*items: ReportItem) -> Report:
    """造一份报告。"""
    report = Report(mc_version="26.3", loader=Loader.FABRIC, profile_name="demo",
                    generated_at="2026-10-01T00:00:00+08:00")
    for item in items:
        report.add(item)
    return report


def test_plan_only_takes_ready_and_degraded(tmp_path: Path) -> None:
    """六组各一条：只有 🟢/🟡 进计划，其余按组记跳过原因。"""
    ready = version("26.3", files=(file_info("carpet-26.3.jar", primary=True),))
    old = version("26.1", files=(file_info("carpet-26.1.jar", primary=True),))
    report = make_report(
        report_item(entry("carpet", slug="carpet"), Status.READY, latest=ready),
        report_item(entry("sodium", slug="sodium"), Status.DEGRADED, latest=ready, compat=old),
        report_item(entry("create"), Status.BLOCKED, latest=old),
        report_item(entry("beta"), Status.PRERELEASE, latest=old),
        report_item(entry("unknown"), Status.UNKNOWN),
        report_item(entry("old"), Status.IGNORED, latest=old),
    )
    plan = plan_for(report, tmp_path)
    # 计划沿用报告的组顺序（🟡 在 🟢 前面），所以 sodium 先于 carpet
    assert [item.entry.key for item in plan.items] == ["sodium", "carpet"]
    assert [reason for _, reason in plan.skipped] == [
        "download.skip.status.blocked", "download.skip.status.prerelease",
        "download.skip.status.unknown", "download.skip.status.ignored",
    ]
    assert DOWNLOADABLE == (Status.READY, Status.DEGRADED)


def test_ready_takes_latest_and_degraded_takes_compat(tmp_path: Path) -> None:
    """🟢 取 latest_for_loader，🟡 取 latest_compat（PRD §14.1）。"""
    latest = version("26.3", files=(file_info("new-26.3.jar", primary=True),))
    compat = version("26.1", files=(file_info("old-26.1.jar", primary=True),))
    report = make_report(
        report_item(entry("a"), Status.READY, latest=latest, compat=compat),
        report_item(entry("b"), Status.DEGRADED, latest=latest, compat=compat),
    )
    plan = plan_for(report, tmp_path)
    by_key = {item.entry.key: item for item in plan.items}
    assert by_key["a"].version is latest and by_key["a"].target.name == "new-26.3.jar"
    assert by_key["b"].version is compat and by_key["b"].target.name == "old-26.1.jar"


def test_degraded_without_compat_is_skipped(tmp_path: Path) -> None:
    """🟡 但「可用」版本缺失 -> 跳过（PRD §14.5 第 17 条）。"""
    report = make_report(report_item(entry("a"), Status.DEGRADED, latest=version("26.3")))
    plan = plan_for(report, tmp_path)
    assert plan.items == ()
    assert plan.skipped[0][1] == "download.skip.no_version"


def test_pick_file_prefers_primary_jar() -> None:
    """只下 primary 的 .jar；附加文件（sources）不算（D49）。"""
    version_with = version("1.0", files=(
        file_info("mod-1.0-sources.jar"),
        file_info("mod-1.0.jar", primary=True),
    ))
    assert pick_file(version_with).filename == "mod-1.0.jar"


def test_pick_file_falls_back_to_first_jar() -> None:
    """没有 primary 标记时取第一个 .jar（跳过非 jar 的附件）。"""
    version_with = version("1.0", files=(
        file_info("mod-1.0.zip"),
        file_info("mod-1.0.jar"),
        file_info("mod-1.0-dev.jar"),
    ))
    assert pick_file(version_with).filename == "mod-1.0.jar"


def test_pick_file_without_jar(tmp_path: Path) -> None:
    """一个 .jar 都没有 -> 跳过并记原因（PRD §14.5 第 2 条）。"""
    empty = version("1.0", files=(file_info("mod-1.0.zip"),))
    assert pick_file(empty) is None
    report = make_report(report_item(entry("a"), Status.READY, latest=empty))
    plan = plan_for(report, tmp_path)
    assert plan.items == () and plan.skipped[0][1] == "download.skip.no_jar"


def test_pick_version_other_statuses() -> None:
    """非 🟢/🟡 的组没有可下载版本。"""
    item = report_item(entry("a"), Status.PRERELEASE, latest=version("1.0"))
    assert pick_version(item) is None


def test_filename_fallback_uses_slug_and_version() -> None:
    """文件名为空 -> {slug}-{version_number}.jar（PRD §14.5 第 3 条）。"""
    version_info = version("26.3")
    assert fallback_filename(entry("carpet", slug="Carpet-Project"), version_info) == (
        "Carpet-Project-26.3.jar")
    assert fallback_filename(entry("carpet"), version_info) == "carpet-26.3.jar"
    assert fallback_filename(entry(""), version_info) == "mod-26.3.jar"


def test_filename_fallback_when_version_number_empty() -> None:
    """版本号也拿不到时用 unknown 占位，绝不产生空文件名。"""
    blank = VersionInfo(version_id="", version_number="", name="", project_id="p",
                        date_published="", version_type="release", game_versions=(),
                        loaders=(), files=())
    assert fallback_filename(entry("carpet"), blank) == "carpet-unknown.jar"


def test_plan_uses_fallback_when_file_name_empty(tmp_path: Path) -> None:
    """filename 为空时计划里用兜底名。"""
    item_version = version("26.3", files=(file_info("", primary=True),))
    report = make_report(report_item(entry("carpet", slug="carpet"), Status.READY,
                                     latest=item_version))
    plan = plan_for(report, tmp_path)
    assert plan.items[0].target.name == "carpet-26.3.jar"


def test_plan_joins_target_dir(tmp_path: Path) -> None:
    """target 是 目标目录 / 文件名，且 plan_for 不创建目录。"""
    sub = tmp_path / "downloads"
    report = make_report(report_item(
        entry("a"), Status.READY, latest=version("1.0", files=(file_info("a-1.0.jar"),))))
    plan = plan_for(report, sub)
    assert plan.items[0].target == sub / "a-1.0.jar"
    assert not sub.exists()


def test_safe_filename_basics() -> None:
    """空名兜底、非法字符替换、控制字符替换、首尾处理。"""
    assert safe_filename("", fallback="x-1.0.jar") == "x-1.0.jar"
    assert safe_filename("   ", fallback="x-1.0.jar") == "x-1.0.jar"
    assert safe_filename("  a-1.0.jar  ", fallback="x.jar") == "a-1.0.jar"
    assert safe_filename('a:b*c?d"e<f>g|h.jar', fallback="x.jar") == "a_b_c_d_e_f_g_h.jar"
    assert safe_filename("a" + chr(92) + "b/c.jar", fallback="x.jar") == "a_b_c.jar"
    assert safe_filename("tab" + chr(9) + "name.jar", fallback="x.jar") == "tab_name.jar"
    assert safe_filename("trailing...", fallback="x.jar") == "trailing"


def test_safe_filename_truncates_keeping_jar() -> None:
    """超长名截断到 200 字符且保留 .jar 后缀。"""
    long_name = "m" * 300 + ".jar"
    result = safe_filename(long_name, fallback="x.jar")
    assert len(result) == MAX_FILENAME and result.endswith(".jar")
    no_suffix = safe_filename("n" * 300, fallback="x.jar")
    assert len(no_suffix) == MAX_FILENAME and not no_suffix.endswith(".jar")


def test_safe_filename_never_empty() -> None:
    """全是非法字符时得到替换后的非空名（不产生空文件名）。"""
    result = safe_filename("???", fallback="")
    assert result == "___"
    assert safe_filename("...", fallback="") != ""


def test_conflicts_detects_existing_files(tmp_path: Path) -> None:
    """目标目录里已有同名文件 -> 出现在 conflicts 里。"""
    (tmp_path / "a-1.0.jar").write_bytes(b"x")
    report = make_report(
        report_item(entry("a"), Status.READY, latest=version("1.0", files=(file_info("a-1.0.jar"),))),
        report_item(entry("b"), Status.READY, latest=version("1.0", files=(file_info("b-1.0.jar"),))),
    )
    plan = plan_for(report, tmp_path)
    found = conflicts(plan)
    assert [item.target.name for item in found] == ["a-1.0.jar"]
    assert overwrite_key(found[0]) == "a-1.0.jar"


def test_extra_files_count(tmp_path: Path) -> None:
    """附加文件计数（汇总里的 ℹ 行）。"""
    multi = version("1.0", files=(file_info("a.jar", primary=True), file_info("a-sources.jar")))
    single = version("1.0", files=(file_info("b.jar", primary=True),))
    report = make_report(
        report_item(entry("a"), Status.READY, latest=multi),
        report_item(entry("b"), Status.READY, latest=single),
    )
    assert extra_files_count(plan_for(report, tmp_path)) == 1


def test_part_path_and_empty_plan(tmp_path: Path) -> None:
    """.part 路径与空计划。"""
    assert part_path(tmp_path / "a.jar").name == "a.jar.part"
    plan = DownloadPlan(items=(), skipped=())
    assert conflicts(plan) == () and extra_files_count(plan) == 0
