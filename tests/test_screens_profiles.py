"""R3-A03 / R3-A10：菜单 [3] 的清单列表屏、管理屏导航与新建空清单。"""
from __future__ import annotations

import io
from pathlib import Path

from modcheck.cli.context import AppContext
from modcheck.cli.prompts import Prompter
from modcheck.cli.screens_profiles import QUIT, run_profiles_screen
from modcheck.console import Console
from modcheck.core.models import ModEntry, Settings
from modcheck.storage.profiles import new_profile, profile_path, save_profile


def feed(values: list[str], prompts: list[str] | None = None):
    """注入输入序列；用完后一律返回 q（保证不会挂死）。

    prompts 非空时把每个提问文本也记下来 —— 注入 input_fn 时提示不会进 console 流，
    但"提示逐字对不对"同样是要验收的东西。
    """
    queue = list(values)

    def _input(prompt: str = "") -> str:
        if prompts is not None:
            prompts.append(prompt)
        return queue.pop(0) if queue else "q"

    return _input


def make_ctx(tmp_path: Path, values: list[str] | None = None, provider=None,
             prompts: list[str] | None = None) -> AppContext:
    """最小上下文：console / config_dir / prompter（需要数据源的用例再传 provider）。"""
    console = Console(stream=io.StringIO(), color="never", width=100)
    registry = None
    if provider is not None:
        from modcheck.providers.registry import ProviderRegistry

        registry = ProviderRegistry(providers=[provider])
    return AppContext(settings=Settings(), config_dir=tmp_path, console=console,
                      registry=registry, cache=None, client=None, interactive=True,
                      prompter=Prompter(input_fn=feed(list(values or ["q"]), prompts),
                                        out=console))


def out(ctx: AppContext) -> str:
    """取屏幕输出。"""
    return ctx.console.stream.getvalue()      # type: ignore[attr-defined]


def write_profile(tmp_path: Path, name: str, count: int = 1) -> Path:
    """写一份清单文件。"""
    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)
    profile = new_profile(name)
    profile.mods = [ModEntry(key="m" + str(i), display_name="Mod" + str(i), mod_id="m" + str(i))
                    for i in range(count)]
    path = profile_path(tmp_path / "profiles", name)
    save_profile(profile, path)
    return path


def test_list_screen_verbatim(tmp_path: Path) -> None:
    """列表屏逐字：标题 / 配置目录 / 条目 / [n] / [q]。"""
    write_profile(tmp_path, "服务器A", 120)
    ctx = make_ctx(tmp_path, ["q"])
    assert run_profiles_screen(ctx) == QUIT
    text = out(ctx)
    assert "=== 管理模组清单 ===" in text
    assert "配置目录：" in text and "profiles" in text
    assert "[1] 服务器A（120 个模组，更新于 " in text
    assert "  [1-9] 打开某个清单进行管理" in text
    assert "  [n]   新建空清单" in text
    assert "  [q]   返回主菜单" in text


def test_empty_list_screen_verbatim(tmp_path: Path) -> None:
    """没有任何清单时给专门的 ⚠ 文案。"""
    ctx = make_ctx(tmp_path, ["q"])
    run_profiles_screen(ctx)
    assert "⚠ 这里还没有任何模组清单。选 [n] 新建一个，或回主菜单选 [2] 扫描 mods 文件夹。" in out(ctx)


def test_open_profile_back_to_list_then_quit(tmp_path: Path) -> None:
    """R3-A03 验收：进 [3] → 打开清单 1 → 管理屏 → b 回列表 → q 回主菜单。"""
    write_profile(tmp_path, "服务器A", 5)
    ctx = make_ctx(tmp_path, ["1", "b", "q"])
    assert run_profiles_screen(ctx) == QUIT
    text = out(ctx)
    assert "=== 管理清单「服务器A」（5 个模组）===" in text
    assert "  [b] 返回清单列表" in text
    assert "  [q] 返回主菜单" in text
    assert text.count("=== 管理模组清单 ===") == 2      # b 之后又画了一次列表屏


def test_open_by_full_name(tmp_path: Path) -> None:
    """超过 9 个清单时可以 [m] 输名字（大小写不敏感）。"""
    for index in range(11):
        write_profile(tmp_path, "清单" + str(index), 1)
    ctx = make_ctx(tmp_path, ["m", "清单10", "q", "q"])
    run_profiles_screen(ctx)
    assert "=== 管理清单「清单10」（1 个模组）===" in out(ctx)


def test_unknown_name_lists_available(tmp_path: Path) -> None:
    """手输不存在的清单名 -> 给出可用清单列表，不崩。"""
    write_profile(tmp_path, "服务器A", 1)
    ctx = make_ctx(tmp_path, ["m", "不存在的", "q"])
    run_profiles_screen(ctx)
    assert "✗ 没有名为「不存在的」的清单。可用的清单：服务器A" in out(ctx)


def test_invalid_choices_three_times_returns(tmp_path: Path) -> None:
    """非法输入最多问 3 次，然后回主菜单（没有死胡同）。"""
    write_profile(tmp_path, "服务器A", 1)
    ctx = make_ctx(tmp_path, ["!@#", "!@#", "!@#", "0"])
    assert run_profiles_screen(ctx) == QUIT
    assert "输入错误太多次，返回上一层。" in out(ctx)


def test_new_profile_creates_file(tmp_path: Path) -> None:
    """[n] 新建空清单（R3-A10）：文件创建、0 个模组、逐字成功文案。"""
    ctx = make_ctx(tmp_path, ["n", "服务器B", "q"])
    run_profiles_screen(ctx)
    path = tmp_path / "profiles" / "服务器B.json"
    assert path.exists()
    assert "✓ 已创建空清单「服务器B」（0 个模组）。可以回主菜单选 [2] 把 mods 文件夹的内容扫描进来。" in out(ctx)


def test_new_profile_rejects_bad_and_duplicate(tmp_path: Path) -> None:
    """非法名与重名各自给文案，都不写盘。"""
    write_profile(tmp_path, "服务器A", 1)
    ctx = make_ctx(tmp_path, ["n", "a/b", "服务器A", "服务器C", "q"])
    run_profiles_screen(ctx)
    text = out(ctx)
    assert "✗ 清单名不能为空" in text
    assert "✗ 已经有一个叫「服务器A」的清单了。换一个名字。" in text
    assert (tmp_path / "profiles" / "服务器C.json").exists()


def test_new_profile_appears_in_list(tmp_path: Path) -> None:
    """新建后立刻出现在列表屏（R3-A10 验收）。"""
    ctx = make_ctx(tmp_path, ["n", "服务器B", "q"])
    run_profiles_screen(ctx)
    assert "[1] 服务器B（0 个模组" in out(ctx)


def write_entries(tmp_path: Path, name: str, mods: list[ModEntry]) -> Path:
    """写一份带指定模组的清单。"""
    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)
    profile = new_profile(name)
    profile.mods = mods
    path = profile_path(tmp_path / "profiles", name)
    save_profile(profile, path)
    return path


def many_mods(count: int) -> list[ModEntry]:
    """造 count 条模组记录（modid = m0..mN）。"""
    return [ModEntry(key="m" + str(i), display_name="Mod" + str(i), mod_id="m" + str(i),
                     sources={"modrinth": "slug" + str(i)}, current_version="1.0")
            for i in range(count)]


# ---------------------------------------------------------------- R3-A09 删除清单
def test_delete_profile_requires_exact_name(tmp_path: Path) -> None:
    """输入不符（服务器B）-> 取消，文件仍在。"""
    path = write_entries(tmp_path, "服务器A", many_mods(3))
    ctx = make_ctx(tmp_path, ["1", "d", "服务器B", "q"])
    run_profiles_screen(ctx)
    text = out(ctx)
    assert "⚠ 即将删除清单「服务器A」（3 个模组）。" in text
    assert "   这个操作不能撤销：清单文件会被直接删除，里面记录的中文名、备注、手动指定的平台项目都会一起消失。" in text
    assert "   （不会删除你 mods 文件夹里的任何 jar 文件。）" in text
    assert "已取消，清单没有被删除。（你输入的是「服务器B」，需要完整输入「服务器A」）" in text
    assert path.exists()


def test_delete_profile_with_exact_name(tmp_path: Path) -> None:
    """输入完整名称 -> 文件删除 + 剩余数量正确。"""
    write_entries(tmp_path, "服务器A", many_mods(3))
    write_entries(tmp_path, "测试服", many_mods(1))
    ctx = make_ctx(tmp_path, ["1", "d", "服务器A", "q"])
    run_profiles_screen(ctx)
    assert "✓ 清单「服务器A」已删除。还剩 1 个清单。" in out(ctx)
    assert not (tmp_path / "profiles" / "服务器A.json").exists()
    assert (tmp_path / "profiles" / "测试服.json").exists()


def test_delete_last_profile_counts_zero(tmp_path: Path) -> None:
    """删掉最后一个清单 -> 还剩 0 个清单。"""
    write_entries(tmp_path, "独苗", many_mods(1))
    ctx = make_ctx(tmp_path, ["1", "d", "独苗", "q"])
    run_profiles_screen(ctx)
    assert "✓ 清单「独苗」已删除。还剩 0 个清单。" in out(ctx)


def test_delete_profile_b_cancels(tmp_path: Path) -> None:
    """输入 b 也算取消（PRD §13.4）。"""
    path = write_entries(tmp_path, "服务器A", many_mods(1))
    ctx = make_ctx(tmp_path, ["1", "d", "b", "q"])
    run_profiles_screen(ctx)
    assert "已取消，清单没有被删除。" in out(ctx)
    assert path.exists()


def test_delete_profile_failure_keeps_file(tmp_path: Path, monkeypatch) -> None:
    """删不掉 -> ✗ 文案，文件仍在。"""
    path = write_entries(tmp_path, "服务器A", many_mods(1))

    def boom(*_args, **_kwargs):
        raise OSError("locked")

    monkeypatch.setattr("modcheck.cli.screens_profiles.delete_profile", boom)
    ctx = make_ctx(tmp_path, ["1", "d", "服务器A", "q"])
    run_profiles_screen(ctx)
    text = out(ctx)
    assert "✗ 删除失败：" in text and "清单没有被删除。" in text
    assert path.exists()


def test_delete_profile_quit_returns_to_main_menu(tmp_path: Path) -> None:
    """确认输入处按 q 直接回主菜单，不删任何东西。"""
    path = write_entries(tmp_path, "服务器A", many_mods(1))
    ctx = make_ctx(tmp_path, ["1", "d", "q"])
    assert run_profiles_screen(ctx) == QUIT
    assert path.exists()


# ---------------------------------------------------------------- R3-A08 重命名清单
def test_rename_profile_updates_file_and_name(tmp_path: Path) -> None:
    """成功：文件名与 profile.name 同时更新，旧文件不再存在。"""
    write_entries(tmp_path, "服务器A", many_mods(2))
    ctx = make_ctx(tmp_path, ["1", "r", "主服", "q"])
    run_profiles_screen(ctx)
    assert "✓ 清单「服务器A」已重命名为「主服」。文件也已经改名。" in out(ctx)
    assert not (tmp_path / "profiles" / "服务器A.json").exists()
    new_path = tmp_path / "profiles" / "主服.json"
    assert new_path.exists()
    from modcheck.storage.profiles import load_profile

    assert load_profile(new_path).name == "主服"
    assert len(load_profile(new_path).mods) == 2


def test_rename_profile_prompt_shows_chars(tmp_path: Path) -> None:
    """提示里必须列出非法字符（与校验规则同源）。"""
    write_entries(tmp_path, "服务器A", many_mods(1))
    prompts: list[str] = []
    ctx = make_ctx(tmp_path, ["1", "r", "b", "q"], prompts=prompts)
    run_profiles_screen(ctx)
    wanted = '请输入新的清单名称（不能包含 ' + chr(92) + ' / : * ? " < > | 这些字符），[b] 返回 > '
    assert wanted in prompts


def test_rename_profile_rejects_existing(tmp_path: Path) -> None:
    """重名被拒并给建议，两个文件都不变。"""
    write_entries(tmp_path, "服务器A", many_mods(1))
    write_entries(tmp_path, "测试服", many_mods(1))
    before = (tmp_path / "profiles" / "测试服.json").read_bytes()
    ctx = make_ctx(tmp_path, ["1", "r", "测试服", "q"])
    run_profiles_screen(ctx)
    assert "✗ 已经有一个叫「测试服」的清单了。换一个名字，或先用 [d] 删掉它。" in out(ctx)
    assert (tmp_path / "profiles" / "测试服.json").read_bytes() == before
    assert (tmp_path / "profiles" / "服务器A.json").exists()


def test_rename_profile_rejects_invalid_chars(tmp_path: Path) -> None:
    """非法字符被拒，清单不变。"""
    path = write_entries(tmp_path, "服务器A", many_mods(1))
    before = path.read_bytes()
    ctx = make_ctx(tmp_path, ["1", "r", "a/b", "q"])
    run_profiles_screen(ctx)
    assert "✗ 清单名不能为空" in out(ctx)
    assert path.read_bytes() == before


def test_rename_profile_same_name(tmp_path: Path) -> None:
    """改成同一个名字：明确回执，不写盘。"""
    path = write_entries(tmp_path, "服务器A", many_mods(1))
    before = path.read_bytes()
    ctx = make_ctx(tmp_path, ["1", "r", "服务器A", "q"])
    run_profiles_screen(ctx)
    assert "清单名字没有变化。" in out(ctx)
    assert path.read_bytes() == before


def test_rename_profile_keeps_old_when_save_fails(tmp_path: Path, monkeypatch) -> None:
    """写盘失败：旧文件还在，新文件没生成。"""
    path = write_entries(tmp_path, "服务器A", many_mods(1))
    before = path.read_bytes()

    def boom(*_args, **_kwargs):
        raise OSError("read-only")

    monkeypatch.setattr("modcheck.cli.screens_profiles.save_profile", boom)
    ctx = make_ctx(tmp_path, ["1", "r", "主服", "q"])
    run_profiles_screen(ctx)
    assert "✗ 重命名失败：" in out(ctx)
    assert path.read_bytes() == before
    assert not (tmp_path / "profiles" / "主服.json").exists()


def test_rename_profile_reports_leftover_old_file(tmp_path: Path, monkeypatch) -> None:
    """新文件写好了但旧文件删不掉：必须明确告警（否则会出现两个清单）。"""
    write_entries(tmp_path, "服务器A", many_mods(1))

    def boom(*_args, **_kwargs):
        raise OSError("locked")

    monkeypatch.setattr("modcheck.cli.screens_profiles.delete_profile", boom)
    ctx = make_ctx(tmp_path, ["1", "r", "主服", "q"])
    run_profiles_screen(ctx)
    assert "⚠ 新清单已经写好了，但旧的" in out(ctx)
    assert (tmp_path / "profiles" / "主服.json").exists()


# ---------------------------------------------------------------- R3-A07 忽略 / 取消忽略
def test_ignore_and_unignore(tmp_path: Path) -> None:
    """忽略 -> match_status=ignored；取消忽略 -> 恢复正常判定（两条逐字文案）。"""
    write_entries(tmp_path, "服务器A", many_mods(2))
    ctx = make_ctx(tmp_path, ["1", "4", "1", "1", "q"])
    run_profiles_screen(ctx)
    assert "✓ 已忽略「Mod0」。以后检查不再判定它；列表里会显示在 ⚫ 已忽略组。" in out(ctx)
    assert status_of(tmp_path, "服务器A", 0) == "ignored"

    ctx2 = make_ctx(tmp_path, ["1", "4", "Mod0", "2", "q"])
    run_profiles_screen(ctx2)
    assert "✓ 已取消忽略「Mod0」，下次检查会正常判定它。" in out(ctx2)
    assert status_of(tmp_path, "服务器A", 0) == "manual"


def test_ignore_is_idempotent_and_does_not_rewrite(tmp_path: Path) -> None:
    """已经是已忽略时再忽略：给同样的回执，但不改文件（幂等）。"""
    write_entries(tmp_path, "服务器A", many_mods(1))
    ctx = make_ctx(tmp_path, ["1", "4", "1", "1", "q"])
    run_profiles_screen(ctx)
    path = tmp_path / "profiles" / "服务器A.json"
    after_first = path.stat().st_mtime_ns
    ctx2 = make_ctx(tmp_path, ["1", "4", "1", "1", "q"])
    run_profiles_screen(ctx2)
    assert "✓ 已忽略「Mod0」" in out(ctx2)
    assert path.stat().st_mtime_ns == after_first


def test_ignore_invalid_choice_reprompts(tmp_path: Path) -> None:
    """忽略屏里的非法选择就地重问（最多 3 次）。"""
    write_entries(tmp_path, "服务器A", many_mods(1))
    ctx = make_ctx(tmp_path, ["1", "4", "1", "9", "1", "q"])
    run_profiles_screen(ctx)
    text = out(ctx)
    assert "✗ 没有这个选项，请重新选择。" in text
    assert "✓ 已忽略「Mod0」" in text


def test_ignore_unknown_mod(tmp_path: Path) -> None:
    """定位不到 -> 候选文案，且不问忽略/取消。"""
    write_entries(tmp_path, "服务器A", many_mods(2))
    ctx = make_ctx(tmp_path, ["1", "4", "zzz", "q"])
    run_profiles_screen(ctx)
    text = out(ctx)
    assert "✗ 清单「服务器A」里没有叫「zzz」的模组。" in text
    assert "[1] 忽略它" not in text


# ---------------------------------------------------------------- R3-A06 指定平台项目
def carpet_provider(**kw):
    """带 carpet 项目的假数据源。"""
    from fakes import FakeProvider
    from modcheck.core.models import ProjectInfo

    project = ProjectInfo(project_id="P1", slug="carpet", title="Carpet",
                          description="", project_type="mod", loaders=("fabric",),
                          game_versions=("26.3",), downloads=1, version_count=10)
    kw.setdefault("projects", {"carpet": project})
    provider = FakeProvider(**kw)
    # 指定平台项目只认 modrinth 数据源，所以假数据源要以 modrinth 的身份注册
    provider.name = "modrinth"
    provider.display_name = "Modrinth"
    return provider


def status_of(tmp_path: Path, name: str, index: int = 0) -> str:
    """读回清单里第 index 条的 match_status。"""
    from modcheck.storage.profiles import load_profile

    return load_profile(profile_path(tmp_path / "profiles", name)).mods[index].match_status.value


def sources_of(tmp_path: Path, name: str) -> dict:
    """读回清单里第一条的 sources / match_status。"""
    from modcheck.storage.profiles import load_profile

    entry = load_profile(profile_path(tmp_path / "profiles", name)).mods[0]
    return {"sources": dict(entry.sources), "status": entry.match_status.value, "key": entry.key}


def test_set_source_by_slug(tmp_path: Path) -> None:
    """输入 slug -> 校验存在 -> 写回 sources + manual + 逐字成功文案。"""
    write_entries(tmp_path, "服务器A", many_mods(1))
    ctx = make_ctx(tmp_path, ["1", "3", "1", "carpet", "q"], provider=carpet_provider())
    run_profiles_screen(ctx)
    assert "✓ 已把「Mod0」指定为 Modrinth 项目「Carpet」（carpet）。下次检查直接用这个项目，不再询问。" in out(ctx)
    saved = sources_of(tmp_path, "服务器A")
    assert saved["sources"]["modrinth"] == "carpet"
    assert saved["status"] == "manual"
    assert saved["key"] == "slug:modrinth:carpet"


def test_set_source_by_url(tmp_path: Path) -> None:
    """粘贴 Modrinth 链接同样能解析出 slug（R3-A06 验收）。"""
    write_entries(tmp_path, "服务器A", many_mods(1))
    ctx = make_ctx(tmp_path, ["1", "3", "Mod0", "https://modrinth.com/mod/carpet", "q"],
                   provider=carpet_provider())
    run_profiles_screen(ctx)
    assert sources_of(tmp_path, "服务器A")["sources"]["modrinth"] == "carpet"


def test_set_source_not_found(tmp_path: Path) -> None:
    """项目不存在 -> 中文"找不到"文案，清单不变。"""
    path = write_entries(tmp_path, "服务器A", many_mods(1))
    before = path.read_bytes()
    ctx = make_ctx(tmp_path, ["1", "3", "1", "carpet-xyz", "q"], provider=carpet_provider())
    run_profiles_screen(ctx)
    assert "✗ 在 Modrinth 上找不到「carpet-xyz」。请检查拼写，或直接粘贴项目链接。" in out(ctx)
    assert path.read_bytes() == before


def test_set_source_network_failure(tmp_path: Path) -> None:
    """断网 -> "连不上 Modrinth" 文案，清单不变，退出码不受影响。"""
    from modcheck.errors import ProviderNetworkError

    path = write_entries(tmp_path, "服务器A", many_mods(1))
    before = path.read_bytes()
    provider = carpet_provider(raise_on={"get_project": ProviderNetworkError("offline")})
    ctx = make_ctx(tmp_path, ["1", "3", "1", "carpet", "q"], provider=provider)
    assert run_profiles_screen(ctx) == QUIT
    assert "✗ 现在连不上 Modrinth，没法校验这个项目。请稍后再试。（清单没有改动）" in out(ctx)
    assert path.read_bytes() == before


def test_set_source_bad_input(tmp_path: Path) -> None:
    """非法输入（不是 slug 也不是链接）-> 就地提示，清单不变。"""
    path = write_entries(tmp_path, "服务器A", many_mods(1))
    before = path.read_bytes()
    ctx = make_ctx(tmp_path, ["1", "3", "1", "not a slug!", "q"], provider=carpet_provider())
    run_profiles_screen(ctx)
    assert "✗ 「not a slug!」不像 Modrinth 项目名或链接。" in out(ctx)
    assert path.read_bytes() == before


def test_set_source_unknown_mod(tmp_path: Path) -> None:
    """模组定位不到 -> 候选文案，且不问 slug。"""
    write_entries(tmp_path, "服务器A", many_mods(3))
    ctx = make_ctx(tmp_path, ["1", "3", "zzz", "q"], provider=carpet_provider())
    run_profiles_screen(ctx)
    text = out(ctx)
    assert "✗ 清单「服务器A」里没有叫「zzz」的模组。" in text
    assert "请输入 Modrinth 项目 slug 或链接" not in text


def test_set_source_empty_profile(tmp_path: Path) -> None:
    """空清单：专门文案。"""
    write_entries(tmp_path, "空清单", [])
    ctx = make_ctx(tmp_path, ["1", "3", "q"], provider=carpet_provider())
    run_profiles_screen(ctx)
    assert "这个清单里还没有模组。回上一层用 [b]，或回主菜单选 [2] 扫描 mods 文件夹。" in out(ctx)


# ---------------------------------------------------------------- R3-A05 删除模组
def names(tmp_path: Path, name: str) -> list[str]:
    """读回清单里的 modid 列表（验证磁盘真的变了）。"""
    from modcheck.storage.profiles import load_profile

    return [entry.mod_id or entry.key
            for entry in load_profile(profile_path(tmp_path / "profiles", name)).mods]


def test_remove_mods_with_confirmation(tmp_path: Path) -> None:
    """删 2 条：逐条列出 + 确认后写盘 + 逐字成功文案。"""
    write_entries(tmp_path, "服务器A", many_mods(5))
    ctx = make_ctx(tmp_path, ["1", "2", "1,2", "y", "q"])
    run_profiles_screen(ctx)
    text = out(ctx)
    assert "即将从清单「服务器A」删除 2 个模组：" in text
    assert "    Mod0（m0）" in text and "    Mod1（m1）" in text
    assert "这只会从清单记录里删掉它们：不会删除你 mods 文件夹里的 jar 文件。" in text
    assert "✓ 已删除 2 个模组，清单「服务器A」现在有 3 个模组。（想让它们回来，可以重新扫描 mods 文件夹）" in text
    assert names(tmp_path, "服务器A") == ["m2", "m3", "m4"]


def test_remove_mods_cancelled_keeps_file(tmp_path: Path) -> None:
    """答 n：清单一个字节都不变。"""
    path = write_entries(tmp_path, "服务器A", many_mods(3))
    before = path.read_bytes()
    ctx = make_ctx(tmp_path, ["1", "2", "1", "n", "q"])
    run_profiles_screen(ctx)
    assert "已取消，清单没有被删除。" in out(ctx)
    assert path.read_bytes() == before


def test_remove_mods_default_is_no(tmp_path: Path) -> None:
    """直接回车 = 取消（危险操作绝不默认 Yes）。"""
    path = write_entries(tmp_path, "服务器A", many_mods(3))
    before = path.read_bytes()
    ctx = make_ctx(tmp_path, ["1", "2", "1", "", "q"])
    run_profiles_screen(ctx)
    assert path.read_bytes() == before


def test_remove_mods_unknown_gives_candidates(tmp_path: Path) -> None:
    """定位不到 -> 候选建议文案（D33），且不写盘。"""
    path = write_entries(tmp_path, "服务器A", many_mods(3))
    before = path.read_bytes()
    ctx = make_ctx(tmp_path, ["1", "2", "Mod0x", "2", "Mod", "q"])
    run_profiles_screen(ctx)
    text = out(ctx)
    assert "✗ 清单「服务器A」里没有叫「Mod0x」的模组。" in text
    assert "你要找的是不是：Mod0（modid=m0）、Mod1（modid=m1）、Mod2（modid=m2）？" in text
    assert path.read_bytes() == before
    assert "确认删除？" not in text


def test_remove_mods_by_identifier_and_mixed(tmp_path: Path) -> None:
    """编号与标识可以混着用，同一模组只删一次。"""
    write_entries(tmp_path, "服务器A", many_mods(4))
    ctx = make_ctx(tmp_path, ["1", "2", "m0, m0, Mod3", "y", "q"])
    run_profiles_screen(ctx)
    assert "即将从清单「服务器A」删除 2 个模组：" in out(ctx)
    assert names(tmp_path, "服务器A") == ["m1", "m2"]


def test_remove_mods_empty_profile(tmp_path: Path) -> None:
    """空清单：专门文案，不进入确认流程。"""
    write_entries(tmp_path, "空清单", [])
    ctx = make_ctx(tmp_path, ["1", "2", "q"])
    run_profiles_screen(ctx)
    text = out(ctx)
    assert "这个清单里还没有模组。回上一层用 [b]，或回主菜单选 [2] 扫描 mods 文件夹。" in text
    assert "确认删除？" not in text


def test_remove_mods_back_returns(tmp_path: Path) -> None:
    """输入 b 直接回管理屏，不删除。"""
    path = write_entries(tmp_path, "服务器A", many_mods(2))
    before = path.read_bytes()
    ctx = make_ctx(tmp_path, ["1", "2", "b", "b", "q"])
    run_profiles_screen(ctx)
    assert path.read_bytes() == before


def test_remove_mods_save_failure_keeps_everything(tmp_path: Path,
                                                   monkeypatch) -> None:
    """写盘失败：✗ 文案 + 磁盘与内存都不变。"""
    path = write_entries(tmp_path, "服务器A", many_mods(3))
    before = path.read_bytes()

    def boom(*_args, **_kwargs):
        raise OSError("read-only")

    monkeypatch.setattr("modcheck.cli.screens_profiles.save_profile", boom)
    ctx = make_ctx(tmp_path, ["1", "2", "1", "y", "q"])
    run_profiles_screen(ctx)
    assert "✗ 保存失败：" in out(ctx)
    assert path.read_bytes() == before


def test_remove_mods_quit_returns_to_main_menu(tmp_path: Path) -> None:
    """删除屏里按 q 直接回主菜单。"""
    write_entries(tmp_path, "服务器A", many_mods(2))
    ctx = make_ctx(tmp_path, ["1", "2", "q"])
    assert run_profiles_screen(ctx) == QUIT


# ---------------------------------------------------------------- R3-A04 查看模组列表
def test_view_list_first_page(tmp_path: Path) -> None:
    """第一页 20 条：标题给出 第 1/2 页，表头有「匹配」列，第 21 条不在这一页。"""
    write_entries(tmp_path, "服务器A", many_mods(30))
    ctx = make_ctx(tmp_path, ["1", "1", "q", "q"])
    run_profiles_screen(ctx)
    text = out(ctx)
    assert "清单「服务器A」的模组（共 30 个，第 1/2 页）：" in text
    assert "  [n] 下一页  [p] 上一页  [b] 返回" in text
    assert "匹配" in text and "未匹配" in text      # 表头 + 数据行的匹配列
    assert "m19" in text and "m20" not in text


def test_view_list_paging_and_boundaries(tmp_path: Path) -> None:
    """n 到第 2 页；再 n 提示最后一页；p 回第 1 页；再 p 提示第一页。"""
    write_entries(tmp_path, "服务器A", many_mods(30))
    ctx = make_ctx(tmp_path, ["1", "1", "n", "n", "p", "p", "p", "b", "q"])
    run_profiles_screen(ctx)
    text = out(ctx)
    assert "第 1/2 页" in text and "第 2/2 页" in text
    assert "已经是最后一页了。" in text
    assert "已经是第一页了。" in text
    assert "m29" in text


def test_view_empty_profile(tmp_path: Path) -> None:
    """空清单给专门文案（R3-A04 验收）。"""
    write_entries(tmp_path, "空清单", [])
    ctx = make_ctx(tmp_path, ["1", "1", "q"])
    run_profiles_screen(ctx)
    assert "这个清单里还没有模组。回上一层用 [b]，或回主菜单选 [2] 扫描 mods 文件夹。" in out(ctx)


def test_view_quit_returns_to_main_menu(tmp_path: Path) -> None:
    """查看屏里按 q 直接回主菜单（不是回管理屏）。"""
    write_entries(tmp_path, "服务器A", many_mods(3))
    ctx = make_ctx(tmp_path, ["1", "1", "q"])
    assert run_profiles_screen(ctx) == QUIT
    assert "m2" in out(ctx)


def test_view_invalid_choice_reprompts(tmp_path: Path) -> None:
    """查看屏里的非法输入就地重问，不退出。"""
    write_entries(tmp_path, "服务器A", many_mods(3))
    ctx = make_ctx(tmp_path, ["1", "1", "!@#", "q", "q"])
    run_profiles_screen(ctx)
    text = out(ctx)
    assert "✗ 没有这个选项，请重新选择。" in text
    assert text.count("清单「服务器A」的模组") == 2      # 非法输入后又画了一次


def test_broken_profile_is_listed_not_crashing(tmp_path: Path) -> None:
    """损坏的清单只显示错误，不影响其它清单（也不能崩）。"""
    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)
    (tmp_path / "profiles" / "坏.json").write_text("{ not json", encoding="utf-8")
    write_profile(tmp_path, "服务器A", 1)
    ctx = make_ctx(tmp_path, ["q"])
    assert run_profiles_screen(ctx) == QUIT
    text = out(ctx)
    assert "服务器A" in text and "坏" in text
