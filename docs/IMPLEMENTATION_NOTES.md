# 实现说明（程序员自留）

> 本文件记录**实现层面的决策与取舍**，以及实现过程中发现的文档冲突。
> 需求本身以 `docs/PROJECT_BRIEF.md` / `docs/PRD.md` 为准；工程规范以 `docs/ENGINEERING_CONTRACT.md` 为准。

## 1. 分层与依赖

| 层 | 允许做的事 | 禁止的事 |
|---|---|---|
| `core/` | 纯计算、读 jar、调用**注入**的 Provider | print / input / sys.exit / import 具体 Provider / 联网 |
| `storage/` | 读写配置与清单（一律 UTF-8 + 原子写） | print / input / sys.exit |
| `providers/` | 出网、解析响应、抛领域异常 | 直接写标准流 |
| `cli/` | 全部展示、交互、退出码 | 把业务逻辑写进命令里（逻辑都在 core） |

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
