"""profile 子命令测试：标识匹配、表格对齐、--yes。"""
from __future__ import annotations

import io
from argparse import Namespace

from modcheck.cli.commands.profile import _assemble, find_entry, run_profile
from modcheck.cli.context import build_context
from modcheck.console import Console, display_width, pad
from modcheck.core.models import MatchStatus, ModEntry, SourceKind
from modcheck.storage.profiles import load_profile, new_profile, profile_path, save_profile


class FakeArgs:
    """简易命名空间（直接构造 args，避免走完整 argparse）。"""

    def __init__(self, **kw: object) -> None:
        self.__dict__.update(kw)


def make_ctx(tmp_path):
    """最小上下文（只用于 profile 命令）。"""
    args = Namespace(config_dir=str(tmp_path), debug=False, jobs=None, refresh=False,
                     yes=True, no_color=True)
    return build_context(args, Console(stream=io.StringIO(), color="never", width=100))


def seed(tmp_path) -> None:
    """写一份含中文名与 slug 的清单（放进 ctx 实际使用的 profiles 子目录）。"""
    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)
    profile = new_profile("demo")
    profile.mods = [
        ModEntry(key="slug:modrinth:carpet", display_name="Carpet Mod", cn_name="地毯",
                 mod_id="carpet", file_name="[地毯] fabric-carpet-26.1+v260402.jar",
                 aliases=["fabric-carpet-26.1.jar"],
                 sources={"modrinth": "carpet", "curseforge": None},
                 match_status=MatchStatus.EXACT, source_kind=SourceKind.HASH,
                 current_version="26.1"),
    ]
    save_profile(profile, profile_path(tmp_path / "profiles", "demo"))


def test_find_entry_accepts_any_identifier(tmp_path) -> None:
    """modid / slug / 显示名 / 中文名 / 文件名 / aliases 都能命中（大小写不敏感）。"""
    path = profile_path(tmp_path / "profiles", "demo")
    save_profile(new_profile("demo"), path)
    profile = load_profile(path)
    profile.mods = [ModEntry(key="slug:modrinth:carpet", display_name="Carpet Mod",
                             cn_name="地毯", mod_id="carpet",
                             file_name="[地毯] fabric-carpet-26.1+v260402.jar",
                             aliases=["fabric-carpet-26.1.jar"],
                             sources={"modrinth": "carpet"})]
    for raw in ("carpet", "Carpet", "slug:modrinth:carpet", "Carpet Mod", "地毯",
                "[地毯] fabric-carpet-26.1+v260402.jar", "fabric-carpet-26.1.jar"):
        entry, _ = find_entry(profile, raw)
        assert entry is not None, raw


def test_find_entry_suggests_on_miss(tmp_path) -> None:
    """没命中时给出前缀候选，而不是干巴巴一句"没有"。"""
    path = profile_path(tmp_path / "profiles", "demo")
    save_profile(new_profile("demo"), path)
    profile = load_profile(path)
    profile.mods = [ModEntry(key="slug:modrinth:carpet-extra", display_name="Carpet Extra",
                             mod_id="carpet-extra", sources={"modrinth": "carpet-extra"})]
    entry, suggests = find_entry(profile, "carp")
    assert entry is None
    assert suggests and suggests[0].display_name == "Carpet Extra"


def test_assemble_aligns_columns_by_display_width() -> None:
    """表头与数据行必须逐列对齐（CJK 按 2 列算，不能用 len）。"""
    headers = ("#", "名称", "modid", "来源", "识别方式", "当前版本")
    rows = [("1", "[地毯] Carpet Mod", "carpet", "carpet", "文件指纹", "26.1 (v260402)"),
            ("22", "Very Long Mod Name Here", "x", "y", "名称搜索", "—")]
    widths = [max(display_width(headers[i]), *(display_width(row[i]) for row in rows))
              for i in range(len(headers))]
    head_line = _assemble(headers, widths)
    # 逐列手工拼一遍，断言 _assemble 就是"按显示宽度 pad + 列间 2 空格"
    expected_head = "  " + pad(headers[0].rjust(widths[0]), widths[0]) + "  " + \
        "  ".join(pad(cell, widths[index + 1]) for index, cell in enumerate(headers[1:]))
    assert head_line == expected_head
    for row in rows:
        expected = "  " + pad(row[0].rjust(widths[0]), widths[0]) + "  " + \
            "  ".join(pad(cell, widths[index + 1]) for index, cell in enumerate(row[1:]))
        assert _assemble(row, widths) == expected
        assert display_width(_assemble(row, widths)) == display_width(head_line)


def test_profile_show_row_output_is_aligned(tmp_path) -> None:
    """端到端：profile show 的表头与数据行在同样的列位置开始。"""
    seed(tmp_path)
    ctx = make_ctx(tmp_path)
    run_profile(FakeArgs(action="show", name="demo", target=None, json_out=False), ctx)  # type: ignore[arg-type]
    text = ctx.console.stream.getvalue()  # type: ignore[attr-defined]
    lines = [line for line in text.splitlines() if line.startswith("  ") and line.strip()]
    assert len(lines) >= 2
    header, first = lines[0], lines[1]
    # 名称列显示的是 best_name（有中文名时为中文名）；两行列起点一致
    assert header.index("名称") == first.index("地毯")
    assert header.index("modid") == first.index("carpet")
    assert header.index("来源") > first.index("carpet")   # 来源列在 modid 列之后
    assert display_width(header) == display_width(first)


def test_profile_remove_by_modid(tmp_path) -> None:
    """remove 用 modid 也能删掉（此前只认 display_name）。"""
    seed(tmp_path)
    ctx = make_ctx(tmp_path)
    code = run_profile(FakeArgs(action="remove", name="demo", target="carpet",
                                json_out=False), ctx)  # type: ignore[arg-type]
    assert code == 0
    assert load_profile(profile_path(tmp_path / "profiles", "demo")).mods == []


def test_profile_remove_miss_suggests(tmp_path) -> None:
    """没命中时提示"你是想找…"。"""
    seed(tmp_path)
    ctx = make_ctx(tmp_path)
    try:
        run_profile(FakeArgs(action="remove", name="demo", target="carp",
                             json_out=False), ctx)  # type: ignore[arg-type]
    except Exception as exc:  # ConfigError
        assert "你是想找" in str(exc)
    else:
        raise AssertionError("应当抛出 ConfigError")
