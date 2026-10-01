"""全部用户可见文案（简体中文）。

本模块是全项目唯一允许出现中文字符串字面量的地方（模块 docstring 除外）。
其它模块一律通过 t(key, **kw) / tn(key, n, **kw) 取文案，文案本身与 PRD §5 逐字一致。

约定：key 命名规范为「域.子域.名」；缺失的 key 返回 «key» 并往 stderr 打一次提醒
（只在开发期暴露，正式运行不会因缺文案而崩溃）。
"""
from __future__ import annotations

import sys
from typing import Final

_MESSAGES: Final[dict[str, str]] = {
    # ---------------------------------------------------------------- 应用 / 横幅
    "app.title": "Minecraft 模组版本检查工具",
    "app.banner": "=== Minecraft 模组版本检查工具 v{version} ===",
    "app.config_dir": "配置目录：{path}",
    "app.sources": "数据源：{modrinth}  ｜  {curseforge}",
    "source.modrinth.enabled": "Modrinth 已启用",
    "source.modrinth.disabled": "Modrinth 未启用",
    "source.curseforge.enabled": "CurseForge 已启用",
    "source.curseforge.disabled": "CurseForge 未启用（缺少 API Key）",
    # ---------------------------------------------------------------- 主菜单
    "menu.title": "[{index}] {label}",
    "menu.item.check": "检查模组兼容性          （功能①）",
    "menu.item.scan": "扫描 mods 文件夹建立清单（功能②）",
    "menu.item.manage": "管理模组清单            （功能③：查看/新增/删除/修改/重命名）",
    "menu.item.settings": "设置                    （默认版本、加载器、代理、颜色、并发、缓存）",
    "menu.item.versions": "查看官方游戏版本列表",
    "menu.item.quit": "退出",
    "menu.hint.no_profile": "还没有任何模组清单。先选 [2] 扫描你的 mods 文件夹（通常在 服务端根目录\\mods）。",
    "menu.prompt": "请选择 > ",
    "menu.need_profile": "还没有模组清单，无法检查。要现在扫描 mods 文件夹吗？(Y/n) > ",
    "menu.back": "[b] 返回上一步",
    "menu.quit": "[q] 返回主菜单",
    "menu.invalid_choice": "✗ 没有这个选项，请重新选择。",
    "menu.bye": "再见。",
    # ---------------------------------------------------------------- 报告头
    "report.header.title": "  Minecraft 模组兼容性检查报告",
    "report.header.profile": "  模组清单：{name}（{count} 个模组）",
    "report.header.profile_temp": "  模组清单：{name}（{count} 个模组，临时清单未保存）",
    "report.header.target": "  目标版本：Minecraft {mc}  ｜  服务端加载器：{loader}",
    "report.header.sources": "  数据源：{modrinth}  ｜  {curseforge}",
    "report.header.origin": "  识别来源：Modrinth 文件指纹 {hash}  ｜  jar 内信息 {jar_meta}  ｜  名称搜索 {search}  ｜  文件名猜测 {guess}",
    "report.header.time": "  检查时间：{time}  ｜  用时 {elapsed} 秒  ｜  请求 {requests} 次（缓存命中 {cache_hits} 次）",
    # ---------------------------------------------------------------- 结论行
    "verdict.all_ready": "结论：✅ 可以升级到 Minecraft {mc}（{loader}）—— {total} 个模组全部就绪",
    "verdict.ready_with_degraded": "结论：⚠️ 可以升级到 Minecraft {mc}（{loader}）—— {ready} 个模组就绪，{degraded} 个需要降级或使用测试版（见 🟡 部分）",
    "verdict.blocked": "结论：❌ 现在还不能升级到 Minecraft {mc} —— {total} 个模组中有 {blocked} 个阻塞、{unknown} 个未判定",
    "verdict.incomplete": "结论：⚠️ 不能确定能否升级到 Minecraft {mc} —— {unknown} 个模组未判定，本结论不完整",
    "verdict.all_unknown": "结论：❓ 无法得出结论 —— {total} 个模组全部未判定。请先检查网络或数据源状态。",
    "verdict.all_blocked": "结论：❌ 现在还不能升级到 Minecraft {mc} —— {total} 个模组全部不支持",
    "verdict.all_blocked.hint": "提示：新版本刚发布时模组作者通常需要 1~3 周跟进，可以先用 modcheck versions 看看有没有更新的正式版。",
    "verdict.empty": "结论：⚠️ 这次没有检查任何模组 —— 清单「{name}」里没有任何模组。",
    "verdict.interrupted": "结论：⏹ 检查被中断，结果不完整（已完成 {done}/{total}）。下面只列已查出的问题项。",
    # ---------------------------------------------------------------- 分组标题
    "group.blocked.title": "🔴 阻塞（{count} 个）  这些模组在 MC {mc} + {loader} 下没有任何可用版本，必须先处理",
    "group.degraded.title": "🟡 需降级（{count} 个）  最新版用不了，但有别的版本可用，需要你拍板",
    "group.unknown.title": "⚪ 未判定（{count} 个）  没能查到结果，本报告对它们不下结论（不算失败）",
    "group.ready.title": "🟢 就绪（{count} 个）  已经支持 MC {mc} + {loader}，无需处理",
    "group.ignored.title": "⚫ 已忽略（{count} 个）  不再检查，也不计入统计",
    "group.ready.quiet": "  （{count} 个，已省略明细）",
    "group.symbol.ready": "✓",
    "group.symbol.degraded": "!",
    "group.symbol.blocked": "✗",
    "group.symbol.unknown": "?",
    "group.symbol.ignored": "·",
    # ---------------------------------------------------------------- 条目详情
    "report.item.reason": "          原因：{text}",
    "report.item.available": "          可用：{version}（{date}）",
    "report.item.available_channel": "          可用：{version}（{channel} 通道）—— 稳定性自负",
    "report.item.available_current": "          可用：{version}（{date}）—— 你本地就是这个版本",
    "report.item.advice": "          建议：{text}",
    "report.item.date_unknown": "—",
    "report.item.empty_cell": "—",
    "report.item.current_is_compat": "—— 你本地就是这个版本",
    "report.origin.guess_note": "说明：modid 前面带 ~ 的条目是从文件名猜出来的（没有 jar 文件可读），不一定准确，请人工核对。",
    "report.origin.guess_hint": "提示：补充 jar 文件后重新扫描，可以把这些猜测变成确定结果：modcheck scan \"{dir}\" --profile {profile}",
    # ---------------------------------------------------------------- 原因 / 建议
    "reason.ok": "{loader} 最新版 {version} 已经支持 MC {mc}",
    "advice.ok": "无需处理",
    "reason.old_version_only": "{loader} 最新版 {version} 不支持 MC {mc}",
    "advice.old_version_only": "想换最新版请自行确认是否真的兼容；也可以先用可用的那个版本",
    "advice.old_version_only_wait": "等待作者更新；或在升级前先把这个模组移除",
    "reason.prerelease_only": "没有任何正式版支持 MC {mc}（{loader}），只有测试版支持",
    "advice.prerelease_only": "不想用测试版就等正式版；想升级就用这个测试版（记得先备份存档）",
    "reason.no_loader": "该模组没有 {loader} 版本（它只发布了 {loaders} 版本）",
    "advice.no_loader": "把服务端换成 {suggest}；或确认作者有没有 {loader} 分支",
    "reason.no_loader_unknown": "这个项目没有 {loader} 版本",
    "advice.no_loader_unknown": "改用对应的服务端加载器；或找该模组的 {loader} 版本/替代品",
    "reason.no_mc_version": "最高只支持 MC {max_mc}，没有任何支持 {mc} 的版本",
    "reason.no_mc_version_unknown": "没有任何支持 MC {mc} 的版本",
    "advice.no_mc_version": "等待作者更新；或在升级前先把这个模组移除",
    "reason.not_found": "在 Modrinth 上找不到同名项目（可能已删除、改名，或只发布在 CurseForge）",
    "advice.not_found": "手动去 Modrinth / CurseForge 确认；若只在 CurseForge 上，本工具暂不支持",
    "reason.no_files": "这个项目在 Modrinth 上没有任何可下载文件（可能已经被作者清空了）",
    "advice.no_files": "确认这个模组是否已经被废弃；如果是，考虑从服务器上移除它",
    "reason.error": "{text}",
    "advice.error": "稍后重跑：{command}",
    "reason.unmatched": "Modrinth 上没有完全同名的项目，本工具不会靠猜来匹配",
    "advice.unmatched": "交互运行一次并手动确认：{command}",
    "reason.ignored": "你把这个模组标记为已忽略",
    "advice.ignored": "想恢复：modcheck profile edit {profile}",
    # ---------------------------------------------------------------- 汇总 / 下一步
    "report.summary": "汇总：共 {total_all} 个模组，本次检查 {total_checked} 个  ｜  🟢 就绪 {ready}  ｜  🟡 需降级 {degraded}  ｜  🔴 阻塞 {blocked}  ｜  ⚪ 未判定 {unknown}  ｜  ⚫ 已忽略 {ignored}",
    "report.next.title": "下一步：",
    "report.next.step1": "  1. 先处理上面 🔴 的 {blocked} 个阻塞项（每一行都给了原因和建议）",
    "report.next.step2": "  2. 再拍板 🟡 的 {degraded} 个：能接受旧版/测试版就继续，不能就等作者更新",
    "report.next.step3": "  3. 最后重跑一次，把 ⚪ 的 {unknown} 个查清楚：",
    "report.next.command": "       modcheck check --profile {profile} --mc {mc} --loader {loader} --refresh",
    "report.next.none": "可以开始升级了。升级前记得备份存档和 mods 文件夹。",
    "report.empty.next1": "  1. 扫描你的 mods 文件夹建立清单：",
    "report.empty.command": "       modcheck scan \"{dir}\" --profile {profile}",
    "report.empty.next2": "  2. 再重新运行检查",
    "report.unmatched.note": "提示：{count} 个模组没有找到完全同名的项目，本报告对它们不下结论。",
    "report.unmatched.hint": "     运行交互模式逐个确认：modcheck check --profile {profile} --mc {mc} --loader {loader}",
    # ---------------------------------------------------------------- 进度
    "progress.line.full": "正在检查 {total} 个模组……  [{bar}]  {done}/{total}  当前：{name}  已用 {elapsed} 秒  已发现 {blocked} 个阻塞  预计还需约 {eta} 秒",
    "progress.line.mid": "正在检查 {total} 个模组……  [{bar}]  {done}/{total}  当前：{name}  已用 {elapsed} 秒",
    "progress.line.short": "正在检查 {total} 个模组……  [{bar}]  {done}/{total}  已用 {elapsed} 秒",
    "progress.line.tiny": "检查中 {done}/{total}",
    "progress.simple": "正在检查…",
    "progress.percent": "已检查 {done}/{total}……",
    "progress.interrupted": "已中断（按了 Ctrl+C）。本次检查了 {done}/{total} 个模组，结果不完整，只列已查出的问题项：",
    "progress.rate_limited": "ℹ 被 Modrinth 限流，正在放慢速度重试……",
    "progress.estimating": "正在准备检查……",
    # ---------------------------------------------------------------- 扫描
    "scan.header": "正在扫描：{dir}",
    "scan.read": "  ✓ 读到 {count} 个 jar 文件",
    "scan.hash": "  ✓ 已计算 {count} 个文件的指纹（sha1）",
    "scan.skipped.header": "  ⚠ 跳过 {count} 个：",
    "scan.skipped.item": "      {name}  {reason}",
    "scan.skipped.not_mod": "不是模组（jar 里没有模组元数据）",
    "scan.skipped.disabled": "已禁用的文件（按约定跳过；想检查请去掉 .disabled 后缀）",
    "scan.skipped.broken": "文件损坏（无法作为 zip 打开）",
    "scan.skipped.not_jar": "不是 jar 文件",
    "scan.skipped.duplicate": "与前面的文件是同一个模组（已合并）",
    "scan.subdir": "  ⚠ 发现 {count} 个子文件夹未扫描：{names}（mods 目录下的子文件夹不会被游戏加载，已跳过）",
    "scan.identify.header": "识别结果：",
    "scan.identify.hash": "  ✓ 用 Modrinth 文件指纹精确识别：{count} 个（同时知道了你装的版本号）",
    "scan.identify.meta": "  ✓ 用 jar 内元数据识别：{count} 个",
    "scan.identify.search": "  ✓ 用名称搜索匹配：{count} 个",
    "scan.identify.search_pending": "  ⚠ 未能识别、将用名称搜索匹配：{count} 个",
    "scan.identify.search_pending_item": "      {name}  （jar 内没有模组元数据，文件指纹在 Modrinth 上也没有记录）",
    "scan.dupe.header": "⚠️  有 {count} 个模组存在多个 jar 文件（同一 modid），这可能导致服务器启动失败：",
    "scan.dupe.keep": "      {modid}：保留 {kept}",
    "scan.dupe.extra": "              另有一个 {extra} —— 建议手工删除多余的那个",
    "scan.summary": "清单「{profile}」已更新：新增 {added} 个，合并 {merged} 个，跳过 {skipped} 个，共 {total} 个模组",
    "scan.profile_file": "文件：{path}",
    "scan.offline": "  ⚠ 连不上 Modrinth，本次只用 jar 内信息识别（不影响生成清单，但识别率会低一些）。",
    "scan.profile_not_exist": "没有名为「{name}」的清单，将新建一个。",
    "scan.from_list.header": "正在读取文件名清单：{path}（{lines} 行）",
    "scan.from_list.warn": "  ⚠ 没有 jar 文件，只能靠文件名猜。猜出来的结果请人工核对。",
    "scan.from_list.parsed": "  ✓ 解析出 {total} 个条目，其中 {named} 个猜出了模组名",
    "scan.from_list.identify_header": "识别结果：",
    "scan.from_list.matched": "  ~ {count} 个在 Modrinth 上找到了完全同名的项目（结论可用，但「这个项目」是猜的）",
    "scan.from_list.unmatched": "  ⚠ {count} 个没能匹配（检查时会记为 ⚪ 未判定）",
    "scan.from_list.unnamed": "  ⚠ {count} 个连名字都没解析出来（只记了文件名）",
    "scan.from_list.hint": "提示：把 jar 文件放在一个文件夹里，用 modcheck scan <文件夹> 可以精确识别（文件指纹 + jar 内信息）。",
    "scan.merged_note": "已合并：{file}",
    "scan.noninteractive_unmatched": "  ⚠ {count} 个未能自动匹配，运行交互模式可逐个确认。",
    # ---------------------------------------------------------------- 匹配交互
    "match.warn.title": "⚠️  未找到与「{name}」完全同名的项目",
    "match.candidates.header": "  Modrinth 上搜索到这些相近的项目：",
    "match.candidate.item": "    [{index}] {title}   （{slug}）   下载 {downloads}",
    "match.candidate.line": "    [{index}] {title}   （{slug}）   下载 {downloads}",
    "match.candidate.desc": "        {description}",
    "match.option.select": "  [1-5] 选择对应的项目",
    "match.option.manual": "  [m]   手动输入项目 slug 或 Modrinth 链接",
    "match.option.skip": "  [s]   本次跳过（记为「未判定」，不影响其它模组）",
    "match.option.ignore": "  [i]   永久忽略这个模组（以后不再检查它）",
    "match.option.quit": "  [q]   退出检查（已完成的部分会显示）",
    "match.prompt": "请选择 > ",
    "match.manual.prompt": "请输入项目 slug 或 Modrinth 链接（例如 carpet 或 https://modrinth.com/mod/carpet）：",
    "match.manual.prompt_short": "> ",
    "match.recorded": "✓ 已记录：「{name}」→ Modrinth 项目「{title}」（{slug}）",
    "match.recorded.hint": "  以后检查不再询问。想改可以运行：modcheck profile edit {profile}",
    "match.skipped": "已跳过「{name}」，本次记为 ⚪ 未判定。",
    "match.ignored": "已永久忽略「{name}」，以后不再检查它。",
    "match.ignored.hint": "（想恢复：modcheck profile edit {profile}）",
    "match.noninteractive": "⚠️  未找到与「{name}」完全同名的项目，已按「不猜」原则记为 ⚪ 未判定。",
    "match.summary_hint": "提示：{count} 个模组没有找到完全同名的项目，本报告对它们不下结论。",
    # ---------------------------------------------------------------- 清单 / 版本 / 设置 / 缓存
    "profile.list.header": "共有 {count} 个模组清单（配置目录：{dir}）：",
    "profile.list.item": "  [{index}] {name}  {count} 个模组   更新于 {updated}",
    "profile.list.empty": "还没有任何模组清单。用 modcheck scan <mods 文件夹> --profile <名称> 新建一个。",
    "profile.list.hint": "用 modcheck profile show <名称> 查看内容。",
    "profile.show.header": "清单：{name}（{count} 个模组）",
    "profile.show.time": "创建于 {created}  ｜  更新于 {updated}",
    "profile.show.table_header": "  #   名称                         modid           来源       识别方式      当前版本",
    "profile.show.row": "  {index}   {name}   {modid}   {source}   {origin}   {version}",
    "profile.show.json_hint": "（完整内容用 modcheck profile show {name} --json 输出）",
    "profile.created": "已创建清单「{name}」。",
    "profile.copied": "已复制清单「{src}」为「{dst}」。",
    "profile.renamed": "已把清单「{src}」重命名为「{dst}」。",
    "profile.deleted": "已删除清单「{name}」。",
    "profile.delete_confirm": "确定要删除清单「{name}」吗？此操作不可撤销。(y/N) > ",
    "profile.updated": "清单「{name}」已保存。",
    "profile.added": "已把「{name}」加入清单「{profile}」。",
    "profile.removed": "已从清单「{profile}」移除「{name}」。",
    "profile.entry_not_found": "✗ 清单「{profile}」里没有「{name}」。",
    "profile.name_invalid": "✗ 清单名不能为空，也不能包含 \\ / : * ? \" < > | 这些字符。",
    "versions.header": "官方正式版（来源：Mojang 官方版本清单，已缓存 {hours} 小时）：",
    "versions.item": "  [{index}] {version}      发布于 {date}",
    "versions.cached_now": "刚获取",
    "versions.hint": "（官方清单缓存：modcheck cache clear 可强制刷新）",
    "versions.offline": "⚠ 没取到官方版本列表（网络问题），请手动输入版本号：",
    "config.show.header": "配置文件：{path}",
    "config.show.item": "  {label}：{value}",
    "config.label.default_mc": "默认游戏版本",
    "config.label.default_loader": "默认加载器  ",
    "config.label.color": "颜色        ",
    "config.label.proxy": "代理        ",
    "config.label.concurrency": "并发数      ",
    "config.label.timeout": "超时        ",
    "config.label.cache": "缓存有效期  ",
    "config.label.providers": "数据源      ",
    "config.value.concurrency": "{value}（上限 8，Modrinth 限速 300 次/分钟）",
    "config.value.timeout": "{value} 秒（重试 {retries} 次）",
    "config.value.cache": "官方版本清单 {mojang} 小时 ｜ Modrinth {api} 小时",
    "config.value.not_set": "未设置",
    "config.value.providers": "{modrinth}  ｜  {curseforge}",
    "config.value.cf_hint": "CurseForge 未启用（缺少 API Key，见 modcheck config set curseforge.api_key <KEY>）",
    "config.hint": "修改设置：modcheck config set <键> <值>",
    "config.saved": "已保存：{key} = {value}",
    "config.unknown_key": "✗ 不认识的设置项：「{key}」。可用：{keys}",
    "config.bad_value": "✗ 「{key}」的值不合法：{value}",
    "config.reset_done": "已恢复默认设置：{path}",
    "config.path_line": "{path}",
    "cache.info.header": "缓存目录：{dir}",
    "cache.info.item": "  http      {files} 个文件   {size}   最早 {oldest}   最新 {newest}",
    "cache.info.empty": "  http      0 个文件",
    "cache.info.hint": "清理：modcheck cache clear [--older-than 7d]",
    "cache.cleared": "已清理 {count} 个缓存文件。",
    "size.bytes": "{n} B",
    "size.kb": "{n} KB",
    "size.mb": "{n} MB",
    # ---------------------------------------------------------------- 错误文案
    "err.mc.invalid": "✗ 无法识别的游戏版本：「{value}」。\n  正确格式像 26.3 或 1.21.4。运行 modcheck versions 可以看官方版本号。",
    "err.mc.snapshot": "✗ 「{value}」是快照版本，本工具只检查官方正式版。\n  如果你确实要检查快照，请把版本号填成正式版（例如 26.3），或等它转正。",
    "err.mc.unknown": "✗ 官方版本列表里没有「{value}」。\n  最近的正式版：{recent}（运行 modcheck versions 看全部）",
    "err.loader.unsupported": "✗ 暂不支持加载器「{value}」。目前支持：fabric、neoforge、forge。",
    "err.profile.not_found": "✗ 没有名为「{name}」的清单。可用的清单：{available}",
    "err.profile.none_available": "（一个都没有）",
    "err.profile.exists": "✗ 已存在名为「{name}」的清单。换一个名字，或用 modcheck profile copy 复制。",
    "err.profile.rename_exists": "✗ 已经有一个叫「{name}」的清单了。",
    "err.profile.corrupt": "✗ 清单文件读不了：{path}\n  原因：{detail}（可能是手工编辑时少了逗号）。\n  建议：先用 modcheck profile list 看看其它清单是否正常；修好后重试，或从备份恢复。",
    "err.profile.schema": "✗ 清单文件格式不对：{path} 里没有找到「mods」字段。它可能不是本工具的清单文件，或者被别的程序改过。",
    "err.profile.mutex": "✗ --profile 和 --mods-dir 不能同时使用。",
    "err.profile.read_failed": "✗ 清单文件读不了：{path}（{detail}）",
    "err.dir.not_found": "✗ 找不到文件夹：{path}。请检查路径是否正确（例如 C:\\\\servers\\\\survival\\\\mods）。",
    "err.dir.no_jar": "⚠ 这个文件夹里没有任何 jar 文件（{path}）。如果你选错了文件夹，mods 通常在服务端根目录下。",
    "err.scan.all_broken": "✗ 所有 {count} 个 jar 文件都无法读取（可能都损坏了）。清单未改动。",
    "err.from_list.missing": "✗ 读不到文件名清单：{path}（文件不存在或没有内容）。",
    "err.export.failed": "✗ 导出失败：{path} 写不进去（磁盘满或没有权限）。报告已经在屏幕上输出过了。",
    "err.source.none": "✗ 没有可用的数据源。请检查网络，或运行 modcheck config show 查看配置。",
    "err.source.none.detail": "✗ 没有可用的数据源。CurseForge 需要 API Key（当前未配置），Modrinth {modrinth}。请运行 modcheck config show 检查设置。",
    "err.net.offline": "✗ 连不上 Modrinth（网络不可用或需要代理）。\n  请检查网络，或设置代理：modcheck config set proxy http://127.0.0.1:7890\n  本次没有检查任何模组。",
    "err.net.generic": "网络请求失败（{detail}）",
    "err.http.5xx": "Modrinth 服务端出错（HTTP {status}），不是你的问题，稍后重试即可",
    "err.http.status": "Modrinth 返回了 HTTP {status}",
    "err.rate_limited": "被 Modrinth 限流（请求太频繁），已自动重试仍失败",
    "err.rate_limited.hint": "降低并发重试：modcheck check ... --jobs 2",
    "err.timeout": "查询超时（{timeout} 秒无响应），已自动重试 {retries} 次仍然失败",
    "err.parse.provider": "Modrinth 返回的数据看不懂（可能改版了），已跳过这个模组",
    "err.cert": "HTTPS 证书验证失败（常见原因是系统时间不对或公司网络有代理）",
    "err.hash.miss": "ℹ {file} 的文件指纹在 Modrinth 上没有记录（可能是自己改过或自编译的 jar），将改用名称匹配。",
    "err.jar.broken": "本地 jar 读不了（文件损坏），且没有可用的仓库记录",
    "err.internal": "✗ 程序内部出错（这不应该发生）。请把下面的信息反馈给作者：\n  {detail}",
    "err.cf.no_key": "CurseForge 需要 API Key，当前未启用",
    "err.jobs.range": "✗ --jobs 只能是 {low} 到 {high} 之间的整数。",
    "err.window.range": "✗ --window 只能是 {low} 到 {high} 之间的整数。",
    "err.debug.window_small": "[调试] 窗口过小（{window}）可能漏掉兼容版本，建议保持默认 25。",
    "err.debug.jobs_clamped": "[调试] 并发数已限制为 {high}。",
    "err.debug.no_color": "[调试] 终端不支持颜色，已关闭。",
    "err.debug.traceback": "[调试] 详细堆栈：",
    "err.config_dir.not_writable": "⚠ 配置目录不可写：{old}。已自动改用：{new}（下次可用 --config-dir 指定）",
    "err.no_profile_selected": "✗ 没有可用的模组清单。先运行 modcheck scan <mods 文件夹> --profile <名称>。",
    # ---------------------------------------------------------------- CLI 帮助
    "cli.description": "Minecraft 模组版本兼容性检查工具（升级游戏版本前，先查清模组支不支持）",
    "cli.help.config_dir": "指定配置目录（默认自动探测）",
    "cli.help.debug": "打印调试信息（含详细堆栈）",
    "cli.help.version": "打印版本号并退出",
    "cli.help.no_color": "不使用彩色输出（管道/重定向时自动关闭）",
    "cli.help.quiet": "安静模式：不显示进度条，就绪组只显示数量",
    "cli.cmd.check": "检查模组的兼容性",
    "cli.cmd.scan": "扫描 mods 文件夹建立/合并模组清单",
    "cli.cmd.profile": "管理模组清单（查看/新增/删除/修改/重命名）",
    "cli.cmd.versions": "查看官方正式版列表",
    "cli.cmd.config": "读写设置",
    "cli.cmd.cache": "查看与清理缓存",
    "cli.check.profile": "模组清单名称",
    "cli.check.file": "直接指定清单文件路径",
    "cli.check.mods_dir": "直接检查一个 mods 文件夹（不写盘）",
    "cli.check.mc": "目标游戏版本（例如 26.3）",
    "cli.check.loader": "服务端加载器",
    "cli.check.json": "把报告导出为 JSON 到指定文件",
    "cli.check.md": "把报告导出为 Markdown 到指定文件",
    "cli.check.csv": "把报告导出为 CSV 到指定文件",
    "cli.check.refresh": "忽略缓存，强制重新请求",
    "cli.check.jobs": "并发数（默认 6，上限 8）",
    "cli.check.yes": "非交互模式：所有提问一律取默认值",
    "cli.check.pre": "把测试版（beta/alpha）也算作可用",
    "cli.check.window": "高级选项：每次取多少条版本记录（默认 25）",
    "cli.scan.paths": "要扫描的文件夹（可多个；默认不递归子文件夹）",
    "cli.scan.from_list": "从一个文件名清单文本文件导入（每行一个文件名，仅靠文件名猜）",
    "cli.scan.profile": "把结果合并进这个清单（默认 demo）",
    "cli.scan.new": "强制新建清单（不合并已有内容）",
    "cli.scan.yes": "非交互模式：所有提问一律取默认值",
    "cli.profile.action": "操作：list / show / new / copy / rename / delete / add / remove / edit",
    "cli.profile.name": "清单名称",
    "cli.profile.target": "目标名称（copy / rename 用）",
    "cli.profile.json": "以 JSON 输出",
    "cli.versions.limit": "显示多少个正式版（默认 10）",
    "cli.versions.json": "以 JSON 输出",
    "cli.config.action": "操作：show / set / path / reset",
    "cli.config.key": "设置项名称",
    "cli.config.value": "设置项的新值",
    "cli.cache.action": "操作：info / clear",
    "cli.cache.older_than": "只清理早于这个时间的缓存（例如 7d / 12h）",
    "confirm.continue": "按回车继续…",
    # ---------------------------------------------------------------- 单位
    "unit.seconds": "{value} 秒",
    "unit.count": "{value} 个",
}

_MISSING_REPORTED: set[str] = set()


def _report_missing(key: str) -> None:
    """缺失的 key 只往 stderr 提醒一次，绝不抛异常。"""
    if key in _MISSING_REPORTED:
        return
    _MISSING_REPORTED.add(key)
    try:
        sys.stderr.write("missing i18n key: " + key + "\n")
    except Exception:
        pass


def t(key: str, /, **kw: object) -> str:
    """取一条文案并按关键字参数格式化。

    参数：
        key: 文案键（域.子域.名）。
        kw: 模板里的具名占位符。
    返回：
        格式化后的文案；key 不存在时返回 «key» 并在 stderr 提醒一次。
    """
    template = _MESSAGES.get(key)
    if template is None:
        _report_missing(key)
        return "«" + key + "»"
    if not kw:
        return template
    try:
        return template.format(**kw)
    except (KeyError, IndexError, ValueError):
        _report_missing(key)
        return template


def tn(key: str, n: int, /, **kw: object) -> str:
    """带数量的文案；中文没有复数变化，直接把 n 传进模板。"""
    merged = dict(kw)
    merged["n"] = n
    return t(key, **merged)


def has(key: str) -> bool:
    """判断文案键是否存在。"""
    return key in _MESSAGES


def keys() -> tuple[str, ...]:
    """返回全部文案键（供测试与自检使用）。"""
    return tuple(_MESSAGES)


__all__ = ["t", "tn", "has", "keys"]
