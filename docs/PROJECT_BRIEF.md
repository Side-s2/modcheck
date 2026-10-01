# 项目基线文档（Single Source of Truth）

> 本文档由主 Agent 编写，是与用户逐条确认后的**最终结论**。PM 与程序员子代理的一切工作以此为准。
> 若发现文档内部矛盾或与常识冲突，**记录疑问并优先遵循本文档**，不要自行更改方向。

- 文档版本：v1.0（2026-10-01）
- 工作目录：`D:\Programme\python_prgram\mod-version-checker`
- 状态：已获用户批准，正式开工

---

## 1. 一句话定位

给 Minecraft 服务端服主用的 **CLI 工具**：在升级服务端游戏版本之前，检查自己服务器在用的模组是否都已经支持目标游戏版本与服务端加载器，输出「就绪 / 需降级 / 阻塞」三类清单。

---

## 2. 已与用户确认的决策（不可擅自更改）

| 编号 | 决策 | 结论 |
|---|---|---|
| A1 | CurseForge 数据源 | **本轮不实现**（用户暂无法提供 API Key）。但**必须**预留 Provider 扩展位：抽象接口 + 注册表 + 占位实现 + 明确的待补文档。 |
| A2 | 读取 jar 内部 | **允许**。优先读 jar 内元数据获取真实 modid 与支持版本，文件名解析仅作兜底。 |
| B1 | 判定档次 | **三态**：就绪(绿) / 需降级(黄) / 阻塞(红)。另设「未判定」独立分组用于查询失败，**不得**把网络错误计入红色。 |
| B3 | 加载器范围 | **只做 Fabric、NeoForge、Forge** 三个。代码上以枚举/注册表实现，便于以后加 Quilt 等。 |
| C2 | 配置文件格式 | **JSON + UTF-8（无 BOM）**。 |
| F1 | 打包验证 | 在**本机安装 Python 3.11 + Nuitka 并真实打包验证**（工具链装在工作区 `.toolchain/`，不污染系统）。 |
| F4 | 测试 | **pytest 作为开发依赖**，绝不进入分发包（构建时排除）。 |
| A4 | 项目匹配 | **完全同名（名称不多不少）即认定为正确匹配**；只有当找不到完全同名时才告警并进入交互选择。 |
| G2 | 规模 | 按 **200 个模组以内** 设计（并发/显示/性能）。 |
| 其余 | A3/B2/B4/C1/C3/C4/D1~D5/E1~E3/F2/F3/G1/G3 | 均按主 Agent 推荐执行，见下文各章。 |

---

## 3. 平台实测事实（2026-10-01 实测，必须据此编码）

1. **Minecraft 已改用年份制版本号**：最新正式版为 `26.3`，快照 `26.4-snapshot-2`。历史版本仍为 `1.21.x` 形式。程序**不得**硬编码 `1.x` 正则。
2. **官方版本清单**：`https://piston-meta.mojang.com/mc/game/version_manifest_v2.json`，无需 Key，字段 `latest.release` / `versions[].id` / `versions[].type`（`release` / `snapshot`）。程序只取 `type == "release"`。
3. **Modrinth API**：`https://api.modrinth.com/v2`，**无需 Key**，Python urllib 直连可用。
   - 已实测可用：`/tag/loader`、`/tag/game_version`、`/search`、`/project/{id|slug}`、`/project/{id|slug}/version?game_versions=["26.1"]&loaders=["fabric"]`
   - 加载器标识符为小写：`fabric` / `neoforge` / `forge`
   - 实测样例：项目 `carpet` 在 `game_versions=["26.1"] & loaders=["fabric"]` 下返回 1 个版本，文件名正是 `fabric-carpet-26.1+v260402.jar`（与用户给的例子完全一致）
4. **CurseForge API**：`https://api.curseforge.com/v1`，**无 Key 一律 403**；官网搜索页被 Cloudflare 拦截；第三方代理亦 403。→ 印证 A1 决策。
5. 本机用户环境：Windows，工作区为空目录。Python 3.13.5（仅用于工具链无关的杂项），3.11 由项目自行安装到 `.toolchain/Python311`。有 MinGW-w64 gcc 8.1.0、git、curl、tar。
6. 网络可用，无需代理即可访问 Modrinth 与 Mojang（**但用户侧不保证**，故必须支持代理配置）。

---

## 4. 硬性约束（违反即返工）

1. **零第三方运行时依赖**：只允许 Python 3.11 标准库（`urllib.request` / `json` / `zipfile` / `argparse` / `concurrent.futures` / `dataclasses` / `pathlib` / `hashlib` / `tomllib` / `ctypes` 等）。pytest 仅开发期。
2. **Python 3.11 语法基线**：禁止使用 3.12+ 独有语法（如 PEP 695 `type` 语句、`itertools.batched` 等）。语法糖可用 `match`、`| ` 类型联合、`tomllib`。
3. **Windows 10+ 与 Linux 双平台**：不得使用平台专属 API 而不做 `sys.platform` 分支；路径一律 `pathlib`；文件读写一律显式 `encoding="utf-8"`。
4. **core 层纯净**：`modcheck/core/` 与 `modcheck/storage/` 内**禁止** `print`、`input`、`sys.exit`、直接读写 stdout。所有展示交给 `cli/`。这是未来 GUI 封装的前提。
5. **异常不得裸抛**：网络/解析/IO 错误必须转成领域异常并给出中文可读信息；任何单个模组失败都不能中断整体检查。
6. **文案集中**：所有面向用户的字符串集中在 `modcheck/i18n.py`（本期仅 zh_CN），便于未来做 GUI 与多语言。
7. **不产生垃圾**：临时文件用 `tempfile`；缓存写入需原子（先写 `.tmp` 再 `os.replace`）。

---

## 5. 目录与分层规范

```
mod-version-checker/
├── docs/                       # 文档（PM 产出也放这里）
├── src/modcheck/
│   ├── __init__.py             # __version__
│   ├── __main__.py             # python -m modcheck 入口
│   ├── i18n.py                 # 全部用户可见文案
│   ├── errors.py               # 领域异常
│   ├── core/                   # 纯逻辑：无 I/O、无 print
│   │   ├── models.py           # 数据模型（dataclass + 枚举）
│   │   ├── filename.py         # jar 文件名解析（PCL / 通用格式）
│   │   ├── jarmeta.py          # 读取 jar 内 fabric.mod.json / mods.toml / neoforge.mods.toml / quilt.mod.json
│   │   ├── mcversion.py        # MC 版本解析、排序、比较
│   │   ├── matching.py         # 名称规范化 + 完全同名判定 + 候选打分
│   │   ├── checker.py          # 编排：清单 × MC 版本 × 加载器 → 报告
│   │   └── report.py           # 报告数据结构（供 CLI 与未来 GUI 消费）
│   ├── providers/              # 网络数据源
│   │   ├── base.py             # ModProvider 抽象基类 / Protocol
│   │   ├── registry.py         # Provider 注册表（含启用开关）
│   │   ├── http.py             # urllib 封装：超时/重试/代理/UA/JSON/限速
│   │   ├── mojang.py           # 官方版本清单
│   │   ├── modrinth.py         # Modrinth 实现
│   │   └── curseforge.py       # 【占位】CurseForge，未启用，含 TODO 说明
│   ├── storage/
│   │   ├── paths.py            # 便携目录探测 / %APPDATA% 回退 / --config-dir
│   │   ├── settings.py         # settings.json 读写
│   │   └── profiles.py         # 模组清单（profile）读写、增删查改、重命名、合并
│   ├── cache.py                # 文件缓存（TTL + 原子写）
│   ├── console.py              # 颜色/VT 启用/宽度对齐/进度条/降级
│   └── cli/
│       ├── main.py             # argparse 顶层调度
│       ├── menu.py             # 交互式编号菜单（无参数启动时）
│       ├── prompts.py          # 交互询问封装（可注入假输入以便测试）
│       └── commands/
│           ├── check.py
│           ├── scan.py
│           ├── profile.py
│           ├── versions.py
│           ├── config.py
│           └── export.py
├── tests/                      # pytest，离线 fixture 为主
├── build/                      # Nuitka 构建脚本
├── pyproject.toml
├── README.md
└── .toolchain/                 # 本机 Python3.11+Nuitka（不入库，.gitignore）
```

**分层依赖方向（严格单向）**：`cli → core ← providers`、`cli → storage`、`core → models`。
`core` 通过**注入的 Provider 接口**取数据，绝不 import 具体 `providers.modrinth`。

---

## 6. 数据模型契约

### 6.1 settings.json（`<config>/settings.json`）
```json
{
  "schema_version": 1,
  "default_mc_version": null,
  "default_loader": "fabric",
  "color": "auto",
  "proxy": null,
  "concurrency": 6,
  "timeout_seconds": 20,
  "retries": 3,
  "cache_ttl_hours": { "mojang": 24, "api": 6 },
  "providers": {
    "modrinth": { "enabled": true },
    "curseforge": { "enabled": false, "api_key": null }
  }
}
```

### 6.2 模组清单 profile（`<config>/profiles/<名称>.json`）
```json
{
  "schema_version": 1,
  "name": "服务器A",
  "description": "",
  "created_at": "2026-10-01T12:00:00+08:00",
  "updated_at": "2026-10-01T12:00:00+08:00",
  "mods": [
    {
      "key": "carpet",
      "display_name": "Carpet",
      "cn_name": "地毯",
      "mod_id": "carpet",
      "file_name": "fabric-carpet-26.1+v260402.jar",
      "sources": { "modrinth": "carpet", "curseforge": null },
      "detected": {
        "mc_versions": ["26.1"],
        "loaders": ["fabric"],
        "mod_version": "v260402"
      },
      "match_status": "exact",
      "notes": "",
      "added_at": "2026-10-01T12:00:00+08:00",
      "updated_at": "2026-10-01T12:00:00+08:00"
    }
  ]
}
```
- `key`：稳定唯一键。优先用 modid；无 modid 时用「规范化名称」。**合并去重以 key 为准。**
- `match_status`：`exact`（自动完全同名匹配）/ `manual`（用户交互选定）/ `unmatched`（未找到）/ `ignored`（用户永久忽略）。
- `sources.modrinth` 一旦写入即视为权威，后续检查**不再搜索**，直接查该 slug。

### 6.3 检查报告（内存对象，不落盘，可导出）
```
Report {
  mc_version, loader, generated_at,
  groups: { BLOCKED[], DEGRADED[], READY[], UNKNOWN[] },
  summary: { total, ready, degraded, blocked, unknown },
  warnings: [ 前置依赖告警等 ]
}
ReportItem {
  mod (profile 条目), status, reason_code,
  latest_all { version_number, date, game_versions, loaders, channel },
  latest_compat { ... } | null,
  max_supported_mc, message
}
```

---

## 7. 判定规则（精确定义，必须照此实现）

给定目标 MC 版本 `V`、目标加载器 `L`、模组 `M`，取 `M` 的全部版本集合 `Vers`（每项含 `game_versions[]`、`loaders[]`、`date_published`、`version_type`）。

**定义**
- `compat(M,V,L)` ≔ ∃ v ∈ Vers：`V ∈ v.game_versions` 且 `L ∈ v.loaders`
- `latest_all(M)` ≔ Vers 中 `date_published` 最大者
- `latest_compat(M,V,L)` ≔ 满足 compat 的版本中 `date_published` 最大者

**状态表（必须完全按此实现，reason_code 用于测试断言）**

| 状态 | 触发条件 | reason_code |
|---|---|---|
| 🟢 READY | `latest_all(M)` 自身即满足 `V ∈ game_versions` 且 `L ∈ loaders` | `OK` |
| 🟡 DEGRADED | 不满足 READY，但 `compat` 为真（只能停在旧版） | `OLD_VERSION_ONLY` |
| 🟡 DEGRADED | `compat` 为真，但仅 beta/alpha 通道存在满足的版本 | `PRERELEASE_ONLY` |
| 🔴 BLOCKED | 项目存在，但完全没有 `L` 加载器的文件 | `NO_LOADER` |
| 🔴 BLOCKED | 有 `L` 的文件，但都不支持 `V`（须附 `max_supported_mc`） | `NO_MC_VERSION` |
| 🔴 BLOCKED | 搜索/解析后确认项目不存在 | `NOT_FOUND` |
| ⚪ UNKNOWN | 网络错误/超时/API 异常 | `ERROR` |
| ⚪ UNKNOWN | 非交互模式下未能精确同名匹配 | `UNMATCHED` |
| ⚪ 其他 | 用户标记 `ignored` | 不参与统计，列表末尾单列 |

**通道（channel）口径**：默认只把 `version_type == "release"` 计入 `compat` 与 `latest_*`。若 release 下无兼容版本而 beta 下存在 → 🟡 `PRERELEASE_ONLY`（文案注明「仅测试版可用」）。`--pre` 可把 beta/alpha 纳入统计。
> 理由：Modrinth 上大量模组把稳定版标为 beta，若一刀切只认 release 会把可用模组误判成红色，导致服主白忙。

**版本包含关系**：不做 MC 版本高低比较，只做**字符串精确包含**（`V in v.game_versions`）。若允许宽松匹配（如列表含 `1.21` 而目标是 `1.21.4`），必须记录 `MC_VERSION_FUZZY` 并在输出中显式标注「模糊匹配」，**不得**静默当成精确命中。

**加载器不匹配**：项目存在且 MC 版本包含 `V`，但没有任何 `L` 的文件（例：只有 Fabric 版而用户选了 NeoForge）→ 🔴 `NO_LOADER`。这是服主最需要知道的结论之一。

---

## 8. 模组名 → 平台项目的匹配流程（决策 A4 的落地）

优先级从高到低：

1. **已有记录**：`sources.modrinth` 非空 → 直接 `/v2/project/<slug>`，不再搜索。
2. **精确同名**：用候选名（依次尝试 `mod_id` → 解析出的 `name` → `display_name`）调用 `/v2/search`（`limit=10`，`facets=[["project_type:mod"]]`），在结果里找 `normalize(slug) == normalize(N)` 或 `normalize(title) == normalize(N)`：
   - 命中**恰好一个** → 自动认定，`match_status="exact"`，把 slug 写回 profile。
   - 命中**多个** → 歧义，进入交互选择。
3. **无精确同名** → **必须告警 + 交互**（用户明确要求：「找不到名称完全一致的模组的时候，弹出这个警告和交互」）：
   - 打印 ⚠️：`未找到与「<名字>」完全同名的项目`
   - 列出 top 5 候选：序号、`title`、`slug`、下载量、一句话简介
   - 选项：`1..5` 选择 ｜ `m` 手动输入 slug 或项目 URL ｜ `s` 本次跳过（标 ⚪ UNMATCHED）｜ `i` 永久忽略（写 `match_status="ignored"`）｜ `q` 退出
   - 选定后 `match_status="manual"` 并写回 profile
4. **非交互模式**（`--yes` 或 stdin 非 TTY）→ **绝不猜**：标 ⚪ `UNMATCHED`，报告末尾汇总「N 个模组未能自动匹配，请交互运行确认」。
   > 有意的保守策略：**误报为绿比误报为红更危险**——服主会以为模组已就绪而直接升级。

`normalize(s)`：转小写 → 删除所有 `-`、`_`、` `、`.` → 比较键。仅用于「完全同名」判断，不用于模糊打分。

---

## 9. 数据源接口约定（Provider 契约）

### 9.1 抽象接口 `providers/base.py`
```python
class ModProvider(Protocol):
    name: str            # "modrinth" / "curseforge"
    display_name: str    # "Modrinth"
    available: bool      # 是否已配置可用（CF 无 key → False）
    def search(self, query: str, limit: int = 10) -> list[ProjectHit]: ...
    def get_project(self, project_id: str) -> ProjectInfo | None: ...
    def get_versions(self, project_id: str) -> list[VersionInfo]: ...
```
- `VersionInfo`：`version_id, version_number, name, date_published, version_type, game_versions[], loaders[], files[], dependencies[]`
- `ProjectHit`：`project_id, slug, title, downloads, description, provider`
- 只抛 `providers.http.ProviderError` 的子类；`core` 只捕获领域异常。

### 9.2 Modrinth（本期唯一实现的网络数据源）
- `GET https://api.modrinth.com/v2/search?query=<name>&limit=10&facets=[["project_type:mod"]]`
- `GET https://api.modrinth.com/v2/project/<slug|id>`
- `GET https://api.modrinth.com/v2/project/<slug|id>/version`（建议拉全量后本地过滤，缓存复用率更高；也可带 `?game_versions=["26.1"]&loaders=["fabric"]`）
- 关键字段：`slug` `title` `loaders[]` `game_versions[]` `version_number` `date_published` `version_type` `files[].filename/url` `dependencies[]` `project_id`
- 无需 API Key；`User-Agent` 必须标明程序名与版本。

### 9.3 Mojang 官方版本清单
- `GET https://piston-meta.mojang.com/mc/game/version_manifest_v2.json`
- 只取 `type == "release"`，按 `releaseTime` 倒序。用于交互式版本选择，以及文件名解析时识别 MC 版本 token。

### 9.4 CurseForge（**本期只留空位，不得发起任何网络调用**）
`providers/curseforge.py` 必须存在且满足：
- 类名 `CurseForgeProvider`，实现 `ModProvider` 全部方法，一律抛 `ProviderUnavailable("CurseForge 需要 API Key，当前未启用")`
- `available` 恒为 `False`
- 模块 docstring 写清**未来补全所需的一切**：`x-api-key` 头；Key 来源 `settings.providers.curseforge.api_key` 或环境变量 `CURSEFORGE_API_KEY`；端点 `/v1/mods/search`、`/v1/mods/{id}/files`、`POST /v1/mods/fingerprints`；`gameId=432`、`classId=6`；`modLoaderType` 枚举（1=Forge，4=Fabric，6=NeoForge）；MurmurHash2 指纹算法；以及在 `registry.py` 中启用它的方法。
- `registry.py` 依据 `settings.providers.*` 决定实际参与的数据源；UI 对未启用数据源显示「未启用（缺少 API Key）」，不得报错、不得计入红色。

---

## 10. CLI 命令与交互规范

### 10.1 子命令表（同时服务于脚本与未来 GUI）
| 命令 | 作用 |
|---|---|
| `modcheck` | 无参数 → 进入交互式编号菜单 |
| `modcheck check [--profile NAME] [--file PATH] [--mods-dir DIR] [--mc VER] [--loader {fabric,neoforge,forge}] [--json F] [--md F] [--csv F] [--no-color] [--refresh] [--jobs N] [--yes] [--pre] [--quiet]` | 功能①主检查 |
| `modcheck versions [--limit N] [--json]` | 列出官方正式版本 |
| `modcheck scan <DIR> [<DIR>...] [--profile NAME] [--new] [--yes]` | 功能②扫描 mods 文件夹建立/合并清单 |
| `modcheck profile list\|show\|new\|copy\|rename\|delete\|add\|remove\|edit` | 功能③清单增删查改与重命名 |
| `modcheck config show\|set\|path\|reset` | 设置项读写 |
| `modcheck cache info\|clear` | 缓存查看与清理 |

### 10.2 交互式主菜单
```
=== Minecraft 模组版本检查工具 v0.1.0 ===
配置目录：<config 路径>

[1] 检查模组兼容性          （功能①）
[2] 扫描 mods 文件夹建立清单（功能②）
[3] 管理模组清单            （功能③：查看/新增/删除/修改/重命名）
[4] 设置                    （默认版本、加载器、代理、颜色、并发、缓存）
[5] 查看官方游戏版本列表
[0] 退出
请选择 >
```
每次操作结束回到主菜单；`Ctrl+C` 优雅退出（返回码 130），**不得**打印 Python traceback。

### 10.3 交互式检查（功能①）流程
1. 选择模组清单（列 `config/profiles/*.json` 编号选择；也允许输入任意路径）
2. 选择游戏版本（列最近 N 个正式版编号选择；允许手动输入）
3. 选择服务端加载器（Fabric / NeoForge / Forge）
4. 确认后开始检查并显示进度
5. 分组输出报告（排版见第 13 节）
6. 询问是否导出报告 / 是否返回主菜单

### 10.4 退出码约定（便于脚本与未来 GUI）
`0` 全部就绪；`1` 存在阻塞项；`2` 存在未判定项且无阻塞；`3` 参数/配置错误；`4` 数据源整体不可用；`130` 用户中断。

---

## 11. 模组文件名解析规则（**重要**）

用户给出的两种命名格式：
- **PCL 格式**：`[中文名] 服务端 名称 游戏版本 模组版本.jar`，实例：`[地毯] fabric-carpet-26.1+v260402.jar`
- **通用格式**：`fabric-carpet-26.1+v260402.jar`

要求：
1. 首先用 **jar 内部元数据**（`fabric.mod.json`、`META-INF/mods.toml`、`META-INF/neoforge.mods.toml`、`quilt.mod.json`）拿到 modid；文件名的 `[中文名]` 作为中文名保留。
2. 文件名解析用于：拿到 modid 之外的展示名、解析 mrpack 或已重命名的 jar。
3. 解析文件名时的模式：`[中文名] <loader>-<name>-<mcver>+v<modver>.jar`，其中：
   - 中括号前缀可有可无、可多个
   - `+` 之前最后一个 `-NN.N` 段是 MC 版本（年份制如 26.1 / 26.1.1 / 26.3 或 1.21.4）
   - `+` 之后是模组版本 `v260402`（也可能是 `-` 分隔）
4. **搜索关键词**（用于 Modrinth search）：
   - 优先用 `fabric.mod.json` 的 `id`（如 `carpet`）
   - 文件名去除 `[中文名]`、去除 `-` 后的 MC 版本段与 `+v...` 后，剩下的 `name`
   - 若搜索结果里存在 slug / title **完全等于**（忽略大小写与 `-`/`_`/` ` 差异）解析出的 name 或 modid → 直接认定匹配，写回 profile
   - 否则弹警告 + 交互选择候选（列出 title / slug / downloads / 简短描述），并提供「手动输入 slug」「跳过」选项
5. 去重合并：相同 modid 或完全相同文件名的条目合并；中文名不同时保留两个（`cn_name` 取非空者，其余并入 notes）。

---

## 12. 网络与缓存
- 默认超时 20s，重试 3 次指数退避（0.5/1/2s）
- 并发：ThreadPoolExecutor，默认并发 6（用户可 `--jobs`），硬上限 8
- 缓存目录：`<config>/cache/http/`，key = sha1(URL)，存 `{url, fetched_at, body}`，TTL 见设置
- Modrinth 官方限速 300 req/min，程序必须遵守；默认并发度足够
- 缓存命中需在 TUI 中显示（可选）

---

## 13. 显示与终端兼容
- 颜色用 ANSI；Windows 需启用 VT：`ctypes` + `SetConsoleMode(ENABLE_VIRTUAL_TERMINAL_PROCESSING)`；失败时自动降级为无颜色（`[就绪]`/`[阻塞]` 文本标签保持可读）
- **绝不在重定向/管道输出时使用颜色**（`sys.stdout.isatty()` 判断 + `NO_COLOR` 环境变量）
- Windows 控制台代码页：启动时尝试 `os.system('chcp 65001')` 或 `ctypes.windll.kernel32.SetConsoleOutputCP(65001)`；失败不影响运行
- CJK 全角字符对齐：显示表格用 wcwidth 逻辑（自实现简单版：`unicodedata.east_asian_width` in ('F','W') 计 2 列）
- 进度显示：>=3 个模组时显示 `[####----] 42/120`，可 `--quiet` 关闭

---

## 14. 打包与测试
- **Nuitka** 打包脚本：`build/nuitka_build.py`，命令行参数 `--onefile`（默认关闭→standalone）、`--output-dir`
- 打包排除：`pytest`、`_pytest`、`unittest`、`pydoc` 等；`--include-package=modcheck`
- 产物：`dist/modcheck/modcheck.exe`（Windows）/ `dist/modcheck.bin`（Linux）
- 测试：
  - `pytest tests/ -m "not live"` 必须全绿（离线，用假 Provider 与 fixture）
  - `pytest tests/ -m live` 可选，真实网络，默认跳过
  - 覆盖率：core 层 >= 80%
- **pytest 绝不能出现在分发包或运行时依赖里**

---

## 15. 模块边界（不做什么）
- ❌ 不做 GUI（但 core 必须可被 GUI 直接调用）
- ❌ 不做 CurseForge 实现（预留 Provider 空位 + 文档说明如何补）
- ❌ 不做模组下载/替换/安装（只报告）
- ❌ 不做依赖关系递归解析（仅对 `fabric.mod.json` 里的 depends 做一层提示）
- ❌ 不写死任何 API Key（用户环境变量或配置文件注入）
- ❌ 不改用户的 mods 文件夹内容（只读）

---

## 16. 附：用户原文需求（不可裁剪）
1. 交互：暂基于命令行，未来需 GUI 封装 → 现在就要保证扩展性
2. 平台：Windows 与 Linux 兼容
3. 语言/打包：Python 3.11 + Nuitka
4. 性质：兼容性（最低 Windows 10）、轻量化、易用性
5. 用户群：MC 服主，升级前检查 mod 是否支持目标版本
6. 功能①：选择游戏版本 + 服务接口（fabric/neoforge/forge） + 模组信息文档 → 自动读取模组 → 从 CurseForge 与 Modrinth 获取最新版本 → 判断所选接口下是否有满足当前游戏版本的模组 → 分行显示模组与当前最新版 → 满足标绿、不满足标红 → 两类分开显示
7. 功能②：创建模组信息文档；选择文件夹（可多次），里面是 jar；文件名自动转模组名并保存到程序配置；重复自动合并
8. 功能③：手动编辑模组信息文档（增删查改）+ 重命名配置
