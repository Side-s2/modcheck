"""T-06 文件名解析测试（基线 §11.2 的 14 条真实样例，一条都不能少）。"""
from __future__ import annotations

import pytest

from modcheck.core.filename import (is_archive_like, is_disabled_like, parse_jar_filename,
                                    split_cn_prefix, strip_archive_suffix)

#: (文件名, 期望 name, 期望 mc, 期望 mod_version, 期望 cn_name)
CASES: list[tuple[str, str | None, str | None, str | None, str | None]] = [
    ("[\u5730\u6bef] fabric-carpet-26.1+v260402.jar", "carpet", "26.1", "v260402", "\u5730\u6bef"),
    ("fabric-carpet-26.1+v260402.jar", "carpet", "26.1", "v260402", None),
    ("journeymap-1.20.1-5.9.18-fabric.jar", "journeymap", "1.20.1", "5.9.18", None),
    ("jei-1.20.1-fabric-15.2.0.27.jar", "jei", "1.20.1", "15.2.0.27", None),
    ("fabric-api-0.92.2+1.20.1.jar", "api", "1.20.1", "0.92.2", None),
    ("modernfix-fabric-5.19.4+mc1.20.1.jar", "modernfix", "1.20.1", "5.19.4", None),
    ("sodium-fabric-0.5.8+mc1.20.1.jar", "sodium", "1.20.1", "0.5.8", None),
    ("servercore-fabric-1.4.6+1.20.1.jar", "servercore", "1.20.1", "1.4.6", None),
    ("c2me-fabric-mc1.20.1-0.2.0+alpha.11.50.jar", "c2me", "1.20.1", "0.2.0+alpha.11.50", None),
    ("lithium-fabric-0.12.1.jar", "lithium", None, "0.12.1", None),
    ("ferritecore-6.0.1-fabric.jar", "ferritecore", None, "6.0.1", None),
    ("chunky-fabric-1.3.146.jar", "chunky", None, "1.3.146", None),
    ("spark-1.10.53-fabric.jar", "spark", None, "1.10.53", None),
    ("cloth-config-11.1.106-fabric.jar", "cloth-config", None, "11.1.106", None),
]


@pytest.mark.parametrize(("filename", "name", "mc", "mod_version", "cn"), CASES)
def test_real_world_filenames(filename: str, name: str | None, mc: str | None,
                              mod_version: str | None, cn: str | None) -> None:
    """14 条真实文件名样例。"""
    parsed = parse_jar_filename(filename)
    assert parsed.name == name
    assert parsed.mc_version == mc
    assert parsed.mod_version == mod_version
    assert parsed.cn_name == cn
    assert parsed.confidence == "low"


def test_fabric_api_candidates() -> None:
    """fabric-api 的完整形态必须在候选里。"""
    parsed = parse_jar_filename("fabric-api-0.92.2+1.20.1.jar")
    assert "fabric-api" in parsed.name_candidates
    assert parsed.mc_version == "1.20.1"


def test_servercore_mc_is_not_mod_version() -> None:
    """绝不能把 1.4.6 当成 MC 版本。"""
    parsed = parse_jar_filename("servercore-fabric-1.4.6+1.20.1.jar")
    assert parsed.mc_version == "1.20.1"
    assert parsed.mc_version != "1.4.6"


def test_lithium_has_no_mc_version() -> None:
    """文件名里没有 MC 版本时必须为 None，不许猜。"""
    parsed = parse_jar_filename("lithium-fabric-0.12.1.jar")
    assert parsed.mc_version is None
    assert "lithium" in parsed.name_candidates


def test_known_versions_anchor() -> None:
    """给了官方清单时只认清单（1.10.53 不是 MC 版本）。"""
    parsed = parse_jar_filename("spark-1.10.53-fabric.jar",
                                known_mc_versions={"1.10.2", "1.20.1", "26.1", "26.3"})
    assert parsed.mc_version is None
    assert parsed.name == "spark"


def test_multiple_cn_prefixes() -> None:
    """多个前导中文名：第一个为主名，其余进 extra_cn_names。"""
    parsed = parse_jar_filename("[\u5730\u6bef][\u5907\u7528] fabric-carpet-26.1+v260402.jar")
    assert parsed.cn_name == "\u5730\u6bef"
    assert parsed.extra_cn_names == ("\u5907\u7528",)
    assert parsed.name == "carpet"


def test_disabled_and_archive_helpers() -> None:
    """后缀剥离与禁用判断。"""
    assert strip_archive_suffix("a.jar.disabled") == "a"
    assert strip_archive_suffix("a.jar") == "a"
    assert strip_archive_suffix("a.zip") == "a"
    assert strip_archive_suffix("a.txt") == "a.txt"
    assert is_archive_like("a.jar") is True
    assert is_archive_like("a.txt") is False
    assert is_disabled_like("a.jar.disabled") is True
    assert is_disabled_like("a.jar") is False


def test_split_cn_prefix_edge_cases() -> None:
    """中文名切分的边界：未闭合、空括号。"""
    assert split_cn_prefix("[a] b") == (["a"], "b")
    assert split_cn_prefix("[] b") == ([], "b")
    assert split_cn_prefix("[unclosed b") == ([], "[unclosed b")
    assert split_cn_prefix("plain") == ([], "plain")


def test_parse_without_known_versions_never_raises() -> None:
    """回归：不传 known_mc_versions 时必须走启发式分支，不许 NameError。

    这是"首次运行、官方清单还没缓存"的合法调用路径。
    """
    parsed = parse_jar_filename("[\u5730\u6bef] fabric-carpet-26.1+v260402.jar",
                                known_mc_versions=None)
    assert parsed.mc_version == "26.1"
    assert parsed.name == "carpet"


@pytest.mark.parametrize(
    ("filename", "expected_name"),
    [
        ("servercore-fabric-1.4.6+1.20.1.jar", "servercore"),
        ("torchmaster-fabric-1.20.1-2.8.0.jar", "torchmaster"),
        ("prefab-1.20.1-1.0.0.jar", "prefab"),
        ("searchlight-fabric-1.20.1-1.0.0.jar", "searchlight"),
        ("architectury-9.2.14-fabric.jar", "architectury"),
        ("resourceful-lib-fabric-2.0.0.jar", "resourceful-lib"),
    ],
)
def test_channel_words_inside_names_are_not_versions(filename: str, expected_name: str) -> None:
    """回归：名字里含 rc/pre/alpha/beta 子串的 token 不能被当成版本号弹掉。

    servercore / torchmaster / searchlight / architectury 都含 "rc"，
    prefab / precise 含 "pre"。只有"自成一段"的通道词才算版本。
    """
    parsed = parse_jar_filename(filename, known_mc_versions={"1.20.1", "26.1", "26.3"})
    assert parsed.name == expected_name
    assert expected_name in parsed.name_candidates
    assert parsed.name_candidates != ()


def test_fabric_api_keeps_both_forms() -> None:
    """回归：剥掉加载器前缀后，候选里必须同时保留完整形态。

    这个模组真的就叫 fabric-api，只给 "api" 会搜不到。
    """
    parsed = parse_jar_filename("fabric-api-0.92.2+1.20.1.jar")
    assert parsed.name_candidates == ("api", "fabric-api")


def test_empty_and_chinese_only_names() -> None:
    """纯中文名 / 无扩展名 / 空串都不许崩。"""
    parsed = parse_jar_filename("[\u5730\u6bef].jar")
    assert parsed.cn_name == "\u5730\u6bef"
    assert parsed.name is None
    assert parsed.name_candidates == ()
    assert parse_jar_filename("").name is None
    assert parse_jar_filename("carpet-26.1").mc_version == "26.1"
