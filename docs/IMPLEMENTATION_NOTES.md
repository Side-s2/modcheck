# 实现说明（程序员自留）

> 本文件记录**实现层面的决策与取舍**，以及实现过程中发现的文档冲突。
> 需求本身以 `docs/PROJECT_BRIEF.md` / `docs/PRD.md` 为准；工程规范以 `docs/ENGINEERING_CONTRACT.md` 为准。

## 1. 分层与依赖

| 层 | 允许做的事 | 禁止的事 |
|---|---|---|
| `core/` | 纯计算、读 jar、调用**注入**的 Provider | print / input / sys.exit / import 具体 Provider / 联网 |
| `storage/` | 读写配置与清单（一律 UTF-8 + 原子写） | print / input / sys.exit |
| `providers/` | 出网、解析响应、抛领域异常 | 直接写标准流 |
| `flows/` | 流程编排：扫描识别、兼容性检查（**注入** Provider 与回调，返回结构化结果） | print / input / sys.exit / import cli（进度走 `on_progress`，取消走 `should_stop`） |
| `cli/` | 解析参数 → 调 flow → 渲染；交互与退出码 | 把流程逻辑写在命令里（流程都在 flows，判定在 core） |

`core/checker.py` 是纯函数判定；`core/checker_run.py` 是编排（并发、省请求、异常隔离）。
拆成两个文件是为了让"判定"可以完全离线单测，不受并发与网络影响。

## 2. 关键取舍

1. **判定只看数组第一个元素**：Modrinth 的 `/project/{id}/version` 已按发布时间倒序，
   日期会并列，自行排序会引入不稳定。代码里没有任何 `sorted(versions)` / `max(date)`，
   并且有 AST 级回归测试守住这条。
2. **分支③/④ 自校验**（主 Agent 的 D26 加固）：不比对 `version_id`，而是直接问
   "这个版本本身支不支持目标 MC + 加载器"。这样即使编排层传错参数（最容易的是把 A2 当 B 传），
   也不会出现"误报为绿"——那是 PRD §1.3 的一票否决级缺陷。
3. **三个查询方法在 `BaseProvider` 里是抽象方法**，故意不给"先拉全量再本地过滤"的默认实现。
   全量拉取实测单模组可达 3736 条 / 6.8 MB，默认实现属于"继承就能用、用了就错"。
   `filter_versions()` 只留给内存假 Provider。
4. **省请求的顺序**：A（目标加载器最新版）→ 若 A[0] 就支持目标版本则**不请求 B**；
   A 为空才请求 A2；A 与 A2 都为空才 `get_project`（`version_count` 只服务 NO_FILES 分支）。
   最坏 3 个请求，正常 1~2 个。
5. **缓存键包含方法 + URL + 规范化请求体**：POST 的 body 不在 URL 里，
   只用 URL 做键会让批量指纹反查的第 2、3 批命中第 1 批的结果（张冠李戴 → 误报）。
6. **`key_of()` 首选平台 slug**：`slug:{provider}:{slug}` → `mod_id` → `sha1:...` → 规范化名称。
   这样"先导入文件名清单、再扫 jar"两条路径能收敛到同一条记录（否则会出现重复条目）。
   `merge_entries()` 另有 slug / modid / sha1 / file_name 四级兜底匹配。
7. **读用户可能手工编辑过的文本文件用 `utf-8-sig`**：Windows 记事本与 PowerShell 写的 UTF-8 带 BOM，
   用 `utf-8` 会把 U+FEFF 粘在第一条记录上，导致它永远匹配不上。
8. **打包目录探测**：Nuitka **不设置** `sys.frozen`，必须用模块级 `__compiled__`；
   且 onefile 的 `sys.executable` 指向解包临时目录（退出即删），所以要用 `sys.argv[0]`。
9. **版本列不画无意义的箭头**：两侧相同时显示 `0.7.0（已是最新）`；
   🟡 且当前版本恰好是"已是最新兼容版"时显示 `X（已是最新正式版）`，不显示像降级的箭头。

## 3. 与文档的出入（按 CONTRACT > BRIEF > PRD > TASKS 处理）

| # | 文档写法 | 我的实现 | 依据 |
|---|---|---|---|
| 1 | T-06 步骤 3：`mod_version = RHS（去前导 v）` | **保留 v**（`v260402` / `v260915`） | BRIEF §11.2 的 14 条样例表、PRD §5.3.1 的 `26.3 (v260915)` 都要求保留 |
| 2 | T-05 验收：`max_release([...26.3-snapshot-2]) == "26.3"` | 返回 `"26.1"` | 26.3 不在入参里，且规则明确"快照不参与" |
| 3 | TASKS §4.2 用例 20：`Carpet TIS Addition` → `ambiguous=True` | **自动认定** `carpet-tis-addition` | BRIEF §8 第 3 步：title 恰好命中 1 个即认定；判 ambiguous 会让用户白干 |
| 4 | PRD §1.3 S13：单模组 ≤ 5 KB | 实测 limit=25 时约 14~30 KB/请求 | 基线 §17.7 实测每条版本记录约 1.1 KB；主 Agent 已裁决改为 ≤3 请求 / ≤150 KB |
| 5 | PRD §5.8：无元数据的 jar 出现在"未能识别"列表；验收用例 23 又要求跳过它 | **跳过**（无元数据且指纹未命中 → "不是模组"） | 验收用例 23 是主 Agent/PM 的验收口径；跳过会在输出里明确列出，不是静默丢数据 |
| 6 | T-09 `classify` 签名没有 `version_count` | 增加 `version_count: int | None = None` | 分支①b（NO_FILES）需要它，否则无法区分"项目已废"与"没有你的加载器" |
| 7 | PRD §5.3 报告头的识别来源是 3 项，§5.4 是 4 项 | 用 4 项（含"名称搜索"） | §5.4 标注为"报告头，永久保留" |

## 4. 第 2 轮：主 Agent 裁决的落地（D29~D39）

| 裁决 | 内容 | 落地位置 | 证据 |
|---|---|---|---|
| D29 | Nuitka 不设 `sys.frozen`，必须用 `__compiled__`；onefile 的 `sys.executable` 指向会被删除的解包临时目录，必须用 `sys.argv[0]` | `storage/paths.py` | 两种打包模式 `config path` 都落在 exe 同级 |
| D30 | `key_of()` 首选平台标识：`slug:{provider}:{slug}` → modid → sha1 → 规范化名称；另有 slug/modid/sha1/文件名 四级兜底匹配 | `storage/profiles.py` | from-list(30) → scan 文件夹 → 「新增 0，合并 30，共 30」（此前是 46） |
| D31 | 读用户可能手工编辑过的文本文件一律 `utf-8-sig` | `scan.py` / `profiles.py` / `settings.py` | 带 BOM 的清单导入后第一条 key 无 U+FEFF |
| D32 | 表格列宽禁止硬编码空格，表头与数据行必须用同一套 `display_width` 列宽 | `cli/commands/profile.py` | 表头与数据行在相同显示列起始 |
| D33 | 条目定位必须接受全部标识（modid/slug/名称/中文名/文件名/aliases），未命中给候选提示 | `profile.find_entry()` | carpet / Carpet / CARPET / 文件名 全部命中 |
| D34 | `check` 默认**不发搜索请求**；显式 `--resolve` 才搜且每模组 ≤2 个候选 | `core/checker_run.py` | search 调用次数 == 0 的单测 |
| D35 | 无元数据且指纹未命中的 jar **必须进清单**（漏掉比多列危险） | `scan._entry_from_filename()` | 4 jar → 清单 4 条 |
| D36 | 窄终端必须真机可用 | `render.layout_widths()` + `Console.wrap()` | 40/60/80/100 列：0 超宽行、0 控制字符 |
| D37 | README 两段式（普通用户 / 开发者），onefile 大小写实测值 | `README.md` | 实测 7 MB |
| D38 | 两条识别路径统一写 **slug**（hash 路径补一次 `GET /project/{id}`） | `scan._resolve_slugs()` | 不变量单测：两路径同一字符串 |
| D39 | **表格单元格截断，说明文字折行**（PRD §5.1 第 11 条据此修订） | `Console.prose()` | 40 列下「最高只支持 MC 26.2…」完整可读 |

### 本轮修掉的一个 P0（值得记住的教训）

无参数启动 → 菜单 [1] → 选清单，会抛 `AttributeError: 'Namespace' object has no attribute 'mc'`
（`main()` 把只有顶层参数的 Namespace 交给了菜单，而菜单要用 check 的参数对象）。
**根因不是某一处取值写错，而是"菜单与子命令共享参数对象"这个设计缺少初始化环节。**
修法是集中式的 `main.apply_menu_defaults()`，而不是零散补 `getattr`。

**教训：只测"函数"不测"入口"会漏掉整整一类缺陷。** 现在 `tests/test_menu_flow.py`
从 `main()` 真实入口覆盖菜单全部 5 个入口，并断言"菜单路径与子命令路径的汇总行逐字相同"。

## 6. 尚未完成

- `tests/record_fixtures.py`（录制真实响应用于 diff 字段变化）—— 可选，未做。
- 渲染 golden 文件逐字节比对 —— 主 Agent 已认可改用结构化断言（更抗时间戳变动），不做。
- Nuitka onefile 在**同一 PowerShell 会话里连续构建**偶发失败（`__constants.h` 找不到 /
  ccache 文件占用），单独重跑即成功。构建脚本已默认 `--remove-output` 并清空输出目录来降低概率。

## 5. 测试口径

- 离线测试用假 Provider / 假 transport，**全程不联网**；真实行为由 `-m live` 的 10 条用例保证。
- `tests/fixtures/*.json` 是按基线 §17 的实测结论**手工构造**的（TASKS §4.3 明确要求，
  避免把 6.8 MB 的真实响应粘进仓库）。
- `tests/make_fixtures.py` 现场生成 jar（含损坏 jar、禁用文件、无元数据 zip），**不提交任何二进制**。

---

## 7. 第 3 轮（R3-A：菜单 [3]/[4] 交互式管理 + M1 三个 core 新模块）

### 7.1 分层与文件

| 文件 | 职责 | 证据 |
|---|---|---|
| `core/profile_ops.py`（新） | 清单的纯函数操作：D33 全标识定位（key→modid→slug→display_name→cn_name→file/aliases，另支持 1 起算编号）、remove/set_source/set_ignored/add/rename/page_of、URL→slug 解析 | 63 条单测；无 print/input/写盘/第三方 import |
| `core/settings_ops.py`（新） | 设置项 setter（每个都返回**新** Settings，dict 字段深拷贝）+ 校验；代理解析 D42 只有这一份实现，`storage/settings.py` 复用 | 62 条单测 |
| `core/downloader.py`（新） | 下载计划（只取 🟢/🟡、只取 primary 主文件的 .jar）＋ `download_all`（jobs=3、每文件重试 2 次退避 1s/2s、429 不计入重试、取消清 .part、单文件失败隔离） | 33 条单测（全程假 fetcher，不联网） |
| `cli/screens_profiles.py`（新） | 菜单 [3]：列表屏 + 管理屏 + 6 个操作 + 新建空清单 | 屏幕级测试（注入 input_fn） |
| `cli/screens_settings.py`（新） | 菜单 [4]：7 个子项 + 重置（[1] 复用 `_screen_version`，加了 `allow_clear`） | 屏幕级测试 |

「操作函数返回新对象」这条是**写盘失败语义**的基础：调用方只在 `save_*` 成功后才采用新对象，
所以"内存与磁盘都不变"是构造上成立的，不需要回滚代码。

### 7.2 本轮落地的裁决与规格解释

| # | 冲突 | 处理 |
|---|---|---|
| 1 | PRD §14.5#2（只有 sources.jar 要跳过）vs §14.2（无 primary 取第一个 .jar） | 主 Agent 裁决：先过滤 `-sources/-javadoc/-dev/-api` 结尾的 jar；过滤后为空则跳过该模组。`is_jar_file()` 实现，含单测 |
| 2 | §14.5#3（filename 为空的兜底）与"没有 .jar 就跳过" | filename 为空的 **primary** 仍算可下载，用 `{slug}-{version_number}.jar` 兜底 |
| 3 | R3-A13「内存回滚」vs PRD §13.3「这次的修改只在本次运行有效」 | 设置**保留内存新值**（PRD 文案为准）；清单类操作丢弃新对象 |
| 4 | R3 §0.2「Windows 才需要替换非法字符」vs PRD §14.5#4 | 无条件替换 `\/:*?"<>|` 与控制字符（产物会被拷到 Windows，Linux 下只是更安全） |
| 5 | PRD §13.4 第 1 条「输入屏 b 与 q 都提示在行尾」vs §13.2 的逐字提示文本 | **逐字文本优先**（Y3 要求 golden 一致）：提示里只写 `[b]`，但 `q` 在每个输入点都有效（有参数化测试证明） |

### 7.3 实现细节与教训

1. **非 TTY 绝不提问**：守卫放在 `Prompter.ask` —— 只有"没注入 input_fn 且 stdin 不是 TTY"时才抛
   `UserCancelled`。注入了假输入（测试范式）就不受影响；管道/重定向下不会挂死。
2. **Windows 只读文件的语义**：`os.replace` **能**替换只读文件，`unlink` **不能**。
   所以"重命名一个只读清单"会得到"新文件写好了、旧文件删不掉"的半成品状态 ——
   这时必须明确告警（`manage.rename.partial`），否则用户会看到两个清单。
3. **改名后管理屏要跟着换名字**：否则下一轮读屏会报"清单文件读不了"。操作函数返回新名字，
   管理屏据此继续（`_manage_screen` 的返回值约定：QUIT=回主菜单 / BACK=回上一层 / 其它=新的清单名）。
4. **删除清单后回列表屏**（清单已经不在了，留在管理屏只会报错）。
5. **模组名统一成「[中文名] 英文名」**（`core.profile_ops.display_name_of`）：PRD §13.2 的删除确认屏
   写的是「[锂] Lithium（lithium）」，用 `best_name` 只会显示「锂」。
6. **提交粒度**：A03 与 A10 合并成一个提交（列表屏的逐字文案里就有 `[n] 新建空清单`，
   拆开会出现"提示了一个还不存在的选项"的中间态）；管理屏的 6 个操作按 A04~A09 逐条长出来。

### 7.4 本轮**没有**做的（按主 Agent 划定范围）

- B 组：`HttpClient.download`（R3-B01，网络流式 + .part + sha1 + 共用限速器）与下载编排 B04~B12；
- 横切 C01/C02/C03（纯控制台可用性实测、分层静态检查测试、README 增补）。
  ⚠️ 我人工核对过 C02 的三条（三个新 core 模块无 print/input/sys.exit、无 `open(`、无第三方 import），
  但没有把它固化成自动化测试 —— B 组那轮补上更合适。

## 8. 第 4 轮（0 期：流程下沉重构 —— 为 Qt GUI 铺路）

> 对应 `docs/GUI_DESIGN.md` §1。目标：**CLI 行为逐字不变**，把"流程编排"从 `cli/commands/`
> 搬到新的 `flows/`，让 GUI 复用同一套流程而不是各写一份。

### 8.1 搬了什么、留在哪

| 新家 | 从哪来 | 说明 |
|---|---|---|
| `flows/scan_flow.py` | `cli/commands/scan.py` 的 9 个纯逻辑函数 | `scan_dirs` / `scan_from_list` / `_resolve_slugs` / `_lookup_hashes` / `_entry_from_hash` / `_entry_from_meta` / `_entry_from_filename` / `_resolve_by_name` / `_merge_duplicates`，外加 `ScanReport` / `SkipItem` / `HASH_BATCH` / `DEFAULT_PROFILE` |
| `flows/check_flow.py` | `cli/commands/check.py` 的非渲染部分 | `load_profile_entries`（原 `_load_profile_entries`）、`run_check_flow`（建 Report + 跑 check_all + 收集统计 + 判数据源可用性）、`source_unavailable`、`CheckStats` |
| `cli/commands/scan.py` | 只留三件事 | 解析参数 → 调 flow（把 console 包成回调）→ 渲染统计：`run_scan` / `scan_progress_callback` / `_print_*` / `_count_lines` |
| `cli/commands/check.py` | 只留三件事 | `run_check`（编排+渲染）、`_progress_line`、`make_interactive_matcher`、`_export`、`_save_if_changed` |

依赖注入：flows **不 import `cli`**（有 AST 测试守着），Provider / 回调 / 探针全部由调用方传入。

### 8.2 与任务书的 5 处出入（请主 Agent 裁决）

| # | 任务书 | 我的实现 | 理由 |
|---|---|---|---|
| 1 | `scan_dirs(directories, *, provider, profiles_dir, ...)` | **没有** `profiles_dir` | 它不写盘（落盘仍在 `run_scan`），加了就是死参数。要统一签名的话我加回去 |
| 2 | `run_check_flow(...) -> Report` | 初版用可选出参 `stats`；**复核轮按裁决改为返回 `CheckOutcome(report, stats)`**（`stats_source` 作入参，`source_unavailable(outcome)` 作退出码 4 的判据） | 出参是 C 习惯，GUI 照着签名写容易漏传；返回值对 CLI 与 GUI 都只有一个入口 |
| 3 | 进度回调 `on_progress(done, total, name)` | 保留它，另加**可选** `on_item(done, total, entry, item)` | 终端的 TTY 进度行要显示「已发现 N 个阻塞」（PRD §5.5），它需要每条的 status；GUI 只用 `on_progress` 即可 |
| 4 | 扫描也要能中途取消 | `ScanReport.cancelled` + 循环内探针（读 jar / 逐目录 / 命名搜索三处） | `cancelled=True` 是"不许落盘"的硬信号；`run_scan` 里加了守卫（CLI 今天不传 `should_stop`，所以这条分支在 CLI 路径上暂不可达） |
| 5 | 只搬列出的函数 | 顺手删掉 `scan_dirs` 的 `known_mc_versions` 死参数（原代码从未使用） | `scan_from_list` 的同名参数**真的在用**，保留 |

### 8.3 中断语义（本次唯一的行为等价重写）

原来 `run_check` 用 `except UserCancelled / KeyboardInterrupt` 自己拼"不完整报告"。
现在由 `run_check_flow` 内部接住这两类中断，返回 `interrupted=True` 的报告（`completed` 仍是已完成条数、
统计字段不填，与旧行为逐字一致），CLI 只负责渲染与退出码 130 —— 这样 GUI 也能拿到同一份"取消后给结果"的语义。
`should_stop` 提前收工时同样标 `interrupted`。

### 8.4 验证证据（本轮）

- `pytest`：**719 → 758 passed**（新增 39 条 flows 单测；`tests/test_scan.py` 改为直接调流程层 API）。
- 13 个 golden 用例：用 `git worktree` 拉出重构前的代码，与重构后**同一配置目录**各跑一遍快照脚本，
  27 个文件（13 用例 × stdout/stderr + manifest）**逐字节一致**；与仓库里已提交的快照也一致
  （配置目录是脚本自己 mkdtemp 的随机路径，只有它需要归一化后再比）。
- 扩展基线：另抓 scan / check 两条**真正跑流水线**的进程内输出（那 13 个用例一条都没覆盖它们），
  30 个场景（含 --mods-dir / 限流 / 退出码 4 / 中断 / 交互匹配 / 导出 / 多目录）逐字节一致。
- 分层自检：`docs/research/36_layering_check.py` 已把 `flows/` 纳入（20 个模块 0 违规），
  并固化成 `tests/test_layering_flows.py`（AST 检查 + 包结构 + 回调参数存在性）。

### 8.5 复核裁决的落地（主 Agent 5 条）

| 裁决 | 处理 |
|---|---|
| 1. `scan_dirs` 不接 `profiles_dir` | 批准，保持现状 |
| 2. 出参 `stats` 改成返回值 | **已改**：`run_check_flow(...) -> CheckOutcome(report, stats)`；入参名 `stats_source`（`HttpClient` 即可），`source_unavailable(outcome)` 判退出码 4 |
| 3. `on_progress` + 可选 `on_item` | 批准，保持现状 |
| 4. 删 `known_mc_versions` 死参数 | 批准，保持现状 |
| 5. `UserCancelled` 被 `check_one` 吞掉 | 认可为**行为与 PRD 不符**，单独一个提交修（见 §9） |

改完后重跑了两套快照：13 个 golden 用例 + 30 个流水线场景**全部逐字节一致** —— 纯 API 形状调整，CLI 行为零变化。

## 9. 第 4 轮补丁（复核裁决 5：交互选 q 必须真的结束检查）

### 9.1 问题（行为与 PRD 不符）

`core/checker_run.check_one` 的兜底 `except Exception` 把 `UserCancelled` 一起吞了：
用户按 q（PRD §5.7「[q] 退出检查（已完成的部分会显示）」）之后，那个模组变成
「⚪ 未判定 + ✗ 程序内部出错（UserCancelled）」，检查还会继续跑完剩下的模组，退出码 2。
我上一轮把它当成"范围外、保持原样"是判断错误 —— 主 Agent 裁决为缺陷，本轮修掉。

### 9.2 修法（最小改动，S4 不受影响）

在 `check_one` 的兜底之前单独 `except UserCancelled: raise`：
只放行**用户主动取消**；`ProviderError` 与其它 `Exception` 仍然吞掉并标 ⚪。
`UserCancelled` 一路上抛到 `run_check_flow` → interrupted 报告 → CLI 退出码 130。

### 9.3 证据

- 新增 `tests/test_interactive_cancel.py`（7 条）：check_one 上抛 / 顺序路径不再问后面的模组 /
  并发路径（jobs>1）同样上抛 / 流程层给 interrupted 报告且 `unknown == 0` /
  CLI 端到端 130 且不出现「⚪ 未判定」与「程序内部出错」/ 取消不写盘 /
  对照组：普通 `RuntimeError` 仍是 ⚪ + 退出码 2（S4 语义不变）。
- 先写测试、在**未修版本**上跑：5 条红（这正是"被吞掉"的证据），再改 core —— 不是先改后补测试。
- 30 个流水线场景重跑：**只有 `check_interactive_quit` 变化**，且变化正是修复目标
  （exit 2 → 130、⚪ → 中断），其余 29 个逐字节一致；脚本 docstring 已标注这条预期差异。
- 13 个 golden 用例不涉及交互路径，复跑仍逐字节一致。

### 9.4 未改（请裁决）

选 q 之后显示的仍是「已中断（按了 Ctrl+C）」（i18n `progress.interrupted`）。
PRD 没有规定 q 之后的横幅文案，我没擅自改文案；要区分 Ctrl+C 与 q 的话是 i18n 一行的事。



