"""R3-A15：PRD §13 的每条文案都能取到，且高风险句逐字一致（golden）。"""
from __future__ import annotations

import re
from pathlib import Path

from modcheck import i18n
from modcheck.core.profile_ops import INVALID_NAME_CHARS
from modcheck.i18n import t

SRC = Path(__file__).resolve().parent.parent / "src" / "modcheck"
PREFIXES = ("manage.", "settings.", "download.", "match.status.", "screen.")
#: 动态拼接出来的 key（源码里不会出现完整字面量）
DYNAMIC_KEYS = frozenset({
    "download.skip.status.blocked", "download.skip.status.prerelease",
    "download.skip.status.unknown", "download.skip.status.ignored",
})

#: PRD §13.2 / §13.3 的全部 key（少一个都算验收不过）
R3_KEYS = (
    "manage.title", "manage.config_dir", "manage.item", "manage.item.nodate",
    "manage.item.broken", "manage.empty", "manage.hint.open", "manage.hint.by_name",
    "manage.hint.new", "manage.hint.quit", "manage.by_name.prompt", "manage.not_found",
    "manage.one.title", "manage.one.view", "manage.one.remove", "manage.one.set_source",
    "manage.one.ignore", "manage.one.rename", "manage.one.delete", "manage.one.back",
    "manage.one.quit", "manage.one.empty",
    "manage.view.title", "manage.view.col.match", "manage.view.hint",
    "manage.view.last_page", "manage.view.first_page",
    "manage.remove.prompt1", "manage.remove.prompt2", "manage.remove.title",
    "manage.remove.item", "manage.remove.note", "manage.remove.confirm",
    "manage.remove.done", "manage.remove.none", "manage.remove.not_found",
    "manage.remove.not_found_hint", "manage.remove.cancelled", "manage.candidate.item",
    "manage.save_failed",
    "manage.source.pick", "manage.source.prompt", "manage.source.done",
    "manage.source.not_found", "manage.source.network", "manage.source.bad_input",
    "manage.source.entry_missing",
    "manage.ignore.pick", "manage.ignore.menu1", "manage.ignore.menu2", "manage.ignore.ask",
    "manage.ignore.done", "manage.ignore.undone", "manage.ignore.entry_missing",
    "manage.rename.prompt", "manage.rename.exists", "manage.rename.done",
    "manage.rename.same", "manage.rename.failed", "manage.rename.partial",
    "manage.delete.warn1", "manage.delete.warn2", "manage.delete.warn3",
    "manage.delete.ask", "manage.delete.prompt", "manage.delete.cancel",
    "manage.delete.done", "manage.delete.failed",
    "manage.new.prompt", "manage.new.done", "manage.new.exists", "manage.new.failed",
    "manage.add.empty", "manage.add.exists", "manage.add.done",
    "screen.too_many_invalid", "screen.not_found_entry",
    "settings.title", "settings.config_file", "settings.item.mc", "settings.item.loader",
    "settings.item.proxy", "settings.item.color", "settings.item.jobs", "settings.item.cache",
    "settings.item.cf", "settings.item.reset", "settings.hint.quit",
    "settings.value.loader", "settings.value.color.auto", "settings.value.color.always",
    "settings.value.color.never", "settings.value.cf.unset", "settings.value.cf.set",
    "settings.mc.done", "settings.mc.cleared",
    "settings.loader.title", "settings.loader.options", "settings.loader.done",
    "settings.loader.cleared",
    "settings.proxy.prompt", "settings.proxy.bad", "settings.proxy.done",
    "settings.proxy.cleared",
    "settings.color.title", "settings.color.item1", "settings.color.item2",
    "settings.color.item3", "settings.color.done", "settings.color.bad",
    "settings.jobs.prompt", "settings.jobs.done", "settings.jobs.range",
    "settings.cache.title", "settings.cache.item1", "settings.cache.item2",
    "settings.cache.prompt", "settings.cache.done", "settings.cache.range",
    "settings.cf.prompt", "settings.cf.done", "settings.cf.cleared",
    "settings.reset.warn1", "settings.reset.warn2", "settings.reset.warn3",
    "settings.reset.ask", "settings.reset.done", "settings.save_failed",
    "match.status.exact", "match.status.manual", "match.status.unmatched",
    "match.status.ignored", "match.status.guess",
    "menu.version.clear",
    "download.skip.user", "download.error.verify", "download.error.write", "download.error.net",
)


def test_all_r3_keys_exist() -> None:
    """PRD §13 用到的 key 一个都不能少。"""
    assert [key for key in R3_KEYS if not i18n.has(key)] == []


def test_every_new_key_is_used_in_src() -> None:
    """反向完整性：新加的 key 不许是死文案（源码里要能找到引用）。"""
    blob = "\n".join(path.read_text(encoding="utf-8")
                     for path in SRC.rglob("*.py") if path.name != "i18n.py")
    dead = [key for key in i18n.keys()
            if key.startswith(PREFIXES) and key not in DYNAMIC_KEYS
            and ('"' + key + '"') not in blob]
    assert dead == []


#: 长得像 key 但不是 key 的字面量（配置文件名之类）
NON_KEYS = frozenset({"settings.json", "settings.json.tmp", "settings.json.bak"})


def test_every_literal_key_in_src_exists() -> None:
    """源码里写死的 manage./settings./download. 字面量都必须有文案。"""
    pattern = re.compile(r'"((?:manage|settings|download|screen)\.[a-z0-9_.]+)"')
    missing: list[str] = []
    for path in SRC.rglob("*.py"):
        if path.name == "i18n.py":
            continue
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            key = match.group(1)
            if key in NON_KEYS or key.endswith("."):
                continue
            if not i18n.has(key):
                missing.append(path.name + ": " + key)
    assert missing == []


# ---------------------------------------------------------------- 清单管理屏（PRD §13.2）
def test_list_screen_verbatim() -> None:
    """列表屏逐字。"""
    assert t("manage.title") == "=== 管理模组清单 ==="
    assert t("manage.item", index=1, name="服务器A", count=120,
             date="2026-10-01 21:40") == "  [1] 服务器A（120 个模组，更新于 2026-10-01 21:40）"
    assert t("manage.empty") == (
        "  ⚠ 这里还没有任何模组清单。选 [n] 新建一个，或回主菜单选 [2] 扫描 mods 文件夹。")
    assert t("manage.hint.open") == "  [1-9] 打开某个清单进行管理"
    assert t("manage.hint.new") == "  [n]   新建空清单"
    assert t("manage.hint.quit") == "  [q]   返回主菜单"


def test_manage_screen_verbatim() -> None:
    """管理屏 8 行逐字。"""
    assert t("manage.one.title", name="服务器A", count=120) == (
        "=== 管理清单「服务器A」（120 个模组）===")
    assert t("manage.one.view") == "  [1] 查看模组列表"
    assert t("manage.one.remove") == "  [2] 删除模组"
    assert t("manage.one.set_source") == "  [3] 指定平台项目（手动匹配）"
    assert t("manage.one.ignore") == "  [4] 忽略 / 取消忽略模组"
    assert t("manage.one.rename") == "  [r] 重命名这个清单"
    assert t("manage.one.delete") == "  [d] 删除这个清单"
    assert t("manage.one.back") == "  [b] 返回清单列表"
    assert t("manage.one.quit") == "  [q] 返回主菜单"


def test_view_screen_verbatim() -> None:
    """查看列表屏逐字。"""
    assert t("manage.view.title", name="服务器A", count=120, page=1, pages=6) == (
        "清单「服务器A」的模组（共 120 个，第 1/6 页）：")
    assert t("manage.view.hint") == "  [n] 下一页  [p] 上一页  [b] 返回"
    assert t("manage.one.empty") == (
        "这个清单里还没有模组。回上一层用 [b]，或回主菜单选 [2] 扫描 mods 文件夹。")
    assert t("manage.view.last_page") == "已经是最后一页了。"
    assert t("manage.view.first_page") == "已经是第一页了。"
    assert t("manage.view.col.match") == "匹配"


def test_remove_screen_verbatim() -> None:
    """删除模组的提示、确认屏、成功语、候选建议逐字。"""
    assert t("manage.remove.prompt1") == (
        "请输入要删除的模组编号（多个用逗号分隔，例如 3,7,12），或直接输入模组名 / modid：")
    assert t("manage.remove.prompt2") == "（输入 [b] 返回）> "
    assert t("manage.remove.title", profile="服务器A", count=2) == (
        "即将从清单「服务器A」删除 2 个模组：")
    assert t("manage.remove.item", name="[锂] Lithium", modid="lithium") == (
        "    [锂] Lithium（lithium）")
    assert t("manage.remove.note") == (
        "这只会从清单记录里删掉它们：不会删除你 mods 文件夹里的 jar 文件。")
    assert t("manage.remove.confirm") == "确认删除？(y/N) > "
    assert t("manage.remove.done", count=2, profile="服务器A", left=118) == (
        "✓ 已删除 2 个模组，清单「服务器A」现在有 118 个模组。"
        "（想让它们回来，可以重新扫描 mods 文件夹）")
    assert t("manage.remove.not_found_hint", profile="服务器A", name="xxx",
             suggest="地毯（modid=carpet）") == (
        "✗ 清单「服务器A」里没有叫「xxx」的模组。你要找的是不是：地毯（modid=carpet）？")
    assert t("manage.candidate.item", name="地毯", modid="carpet") == "地毯（modid=carpet）"


def test_source_screen_verbatim() -> None:
    """指定平台项目的三句逐字。"""
    assert t("manage.source.done", name="Carpet TIS Addition", title="Carpet TIS Addition",
             slug="carpet-tis-addition") == (
        "✓ 已把「Carpet TIS Addition」指定为 Modrinth 项目「Carpet TIS Addition」"
        "（carpet-tis-addition）。下次检查直接用这个项目，不再询问。")
    assert t("manage.source.not_found", slug="carpet-xyz") == (
        "✗ 在 Modrinth 上找不到「carpet-xyz」。请检查拼写，或直接粘贴项目链接。")
    assert t("manage.source.network") == (
        "✗ 现在连不上 Modrinth，没法校验这个项目。请稍后再试。（清单没有改动）")


def test_ignore_screen_verbatim() -> None:
    """忽略 / 取消忽略逐字。"""
    assert t("manage.ignore.menu1") == "[1] 忽略它（以后检查不再判定，也不计入统计）"
    assert t("manage.ignore.menu2") == "[2] 取消忽略（恢复正常的兼容性检查）"
    assert t("manage.ignore.ask") == "请选择 > "
    assert t("manage.ignore.done", name="OldStuff") == (
        "✓ 已忽略「OldStuff」。以后检查不再判定它；列表里会显示在 ⚫ 已忽略组。")
    assert t("manage.ignore.undone", name="OldStuff") == (
        "✓ 已取消忽略「OldStuff」，下次检查会正常判定它。")


def test_rename_screen_verbatim() -> None:
    """重命名逐字（含非法字符清单，必须与校验规则同源）。"""
    chars = " ".join(INVALID_NAME_CHARS)
    assert t("manage.rename.prompt", chars=chars) == (
        '请输入新的清单名称（不能包含 ' + chr(92) + ' / : * ? " < > | 这些字符），[b] 返回 > ')
    assert t("manage.rename.exists", name="测试服") == (
        "✗ 已经有一个叫「测试服」的清单了。换一个名字，或先用 [d] 删掉它。")
    assert t("manage.rename.done", old="服务器A", new="主服") == (
        "✓ 清单「服务器A」已重命名为「主服」。文件也已经改名。")


def test_delete_profile_screen_verbatim() -> None:
    """删除清单的警告与确认逐字。"""
    assert t("manage.delete.warn1", name="服务器A", count=120) == (
        "⚠ 即将删除清单「服务器A」（120 个模组）。")
    assert t("manage.delete.warn2") == (
        "   这个操作不能撤销：清单文件会被直接删除，里面记录的中文名、备注、"
        "手动指定的平台项目都会一起消失。")
    assert t("manage.delete.warn3") == "   （不会删除你 mods 文件夹里的任何 jar 文件。）"
    assert t("manage.delete.ask", name="服务器A") == (
        "如果确定要删除，请输入这个清单的名称（服务器A）：")
    assert t("manage.delete.prompt") == "> "
    assert t("manage.delete.cancel", value="xxx", name="服务器A") == (
        "已取消，清单没有被删除。（你输入的是「xxx」，需要完整输入「服务器A」）")
    assert t("manage.delete.done", name="服务器A", left=1) == (
        "✓ 清单「服务器A」已删除。还剩 1 个清单。")


def test_new_profile_screen_verbatim() -> None:
    """新建空清单逐字。"""
    assert t("manage.new.prompt") == "请输入新清单的名称（例如 服务器B），[b] 返回 > "
    assert t("manage.new.done", name="服务器B") == (
        "✓ 已创建空清单「服务器B」（0 个模组）。可以回主菜单选 [2] 把 mods 文件夹的内容扫描进来。")


# ---------------------------------------------------------------- 设置屏（PRD §13.3）
def test_settings_items_verbatim() -> None:
    """设置主屏 8 项逐字（含对齐空格）。"""
    assert t("settings.title") == "=== 设置 ==="
    assert t("settings.item.mc", value="26.3") == "  [1] 默认游戏版本       26.3"
    assert t("settings.item.loader", value="Fabric（fabric）") == (
        "  [2] 默认加载器         Fabric（fabric）")
    assert t("settings.item.proxy", value="未设置") == "  [3] 代理               未设置"
    assert t("settings.item.color", value="auto（终端支持就用彩色）") == (
        "  [4] 颜色               auto（终端支持就用彩色）")
    assert t("settings.item.jobs", value=6) == "  [5] 并发数             6（上限 8）"
    assert t("settings.item.cache", value="官方版本清单 24 小时 ｜ Modrinth 6 小时") == (
        "  [6] 缓存有效期         官方版本清单 24 小时 ｜ Modrinth 6 小时")
    assert t("settings.item.cf", value="未设置（本期未启用）") == (
        "  [7] CurseForge API Key 未设置（本期未启用）")
    assert t("settings.item.reset") == "  [8] 重置为默认设置"
    assert t("settings.hint.quit") == "  [q] 返回主菜单"


def test_settings_sub_screens_verbatim() -> None:
    """各子屏提示与错误语逐字。"""
    assert t("settings.loader.options") == (
        "  [1] Fabric  [2] NeoForge  [3] Forge  [c] 清除  [b] 返回")
    assert t("settings.proxy.prompt") == (
        "请输入代理地址（例如 http://127.0.0.1:7890）。输入 null 表示不使用代理。[b] 返回 > ")
    assert t("settings.proxy.bad", value="abc") == (
        "✗「abc」不像一个代理地址。正确格式像 http://127.0.0.1:7890。没有改动。")
    assert t("settings.jobs.prompt", value=6) == (
        "请输入并发数（1-8，数字越大越快，但更容易被 Modrinth 限流）。当前 6：[b] 返回 > ")
    assert t("settings.jobs.range", value=12) == (
        "✗ 并发数要在 1 到 8 之间（你输入的是 12）。没有改动。")
    assert t("settings.cache.item1", hours=24) == "  [1] 官方版本清单（当前 24 小时）"
    assert t("settings.cache.item2", hours=6) == "  [2] Modrinth（当前 6 小时）"
    assert t("settings.cache.range", value=200) == (
        "✗ 缓存有效期要在 1 到 168 小时之间（你输入的是 200）。没有改动。")
    assert t("settings.cf.done", mask="****abcd") == (
        "✓ CurseForge API Key 已保存（回显只显示后 4 位：****abcd）。")
    assert t("settings.cf.prompt") == (
        "请输入 CurseForge API Key（输入 null 清除）。"
        "提示：本工具当前没有启用 CurseForge，填了也不会联网，只为以后留用。[b] 返回 > ")
    assert t("settings.save_failed", path="C:/x/settings.json") == (
        "✗ 设置没能保存到 C:/x/settings.json（磁盘满或没有权限）。这次的修改只在本次运行有效。")


def test_reset_screen_verbatim() -> None:
    """重置设置的确认屏逐字。"""
    assert t("settings.reset.warn1") == "⚠ 即将把设置恢复成出厂状态："
    assert t("settings.reset.warn2") == (
        "   默认游戏版本、默认加载器、代理、颜色、并发数、缓存有效期、"
        "CurseForge API Key 都会回到初始值。")
    assert t("settings.reset.warn3") == "   （模组清单和下载缓存不会被删除。）"
    assert t("settings.reset.ask") == "确认重置？(y/N) > "
    assert t("settings.reset.done") == "✓ 设置已重置为默认值。"


def test_version_screen_clear_option_verbatim() -> None:
    """版本屏的 [c] 清除选项逐字（设置屏 [1] 复用）。"""
    assert t("menu.version.clear") == "  [c] 清除（不设默认）"
