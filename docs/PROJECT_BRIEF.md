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

**定义（v1.1 修订：最新版必须按目标加载器过滤）**
- `compat(M,V,L)` ≔ ∃ v ∈ Vers：`V ∈ v.game_versions` 且 `L ∈ v.loaders`
- `latest_for_loader(M,L)` ≔ Vers 中满足 `L ∈ v.loaders` 且发布时间最新的那一条
- `latest_all(M)` ≔ Vers 中发布时间最新的一条（**仅用于展示"该项目全局最新版"，不参与判定**）
- `latest_compat(M,V,L)` ≔ 满足 compat 的版本中发布时间最新的一条

> ⚠️ **实测教训（必须遵守）**：同一模组会为不同加载器发布内容不同、**发布时间完全相同**的版本条目。实测 JourneyMap 有 `26.3-6.0.9+paper` / `26.3-6.0.9+neoforge` / `26.3-6.0.9+forge` / `26.3-6.0.9+fabric` 四条，日期均为 2026-09-19。若按"全局最新"判定会取到 paper 那条，把本该 🟢 就绪的模组**误判成 🟡**。因此**判定一律以 `latest_for_loader` 为准**。
> ⚠️ **排序规则**：`date_published` 会并列。**直接使用 Modrinth API 返回的顺序**（官方已按发布时间倒序），取第一个满足条件者即可；**禁止**自行重新排序或依赖排序稳定性。

**状态表（必须完全按此实现，reason_code 用于测试断言）**

| 状态 | 触发条件 | reason_code |
|---|---|---|
| 🟢 READY | `latest_for_loader(M,L)` 存在，且 `V ∈ its.game_versions` | `OK` |
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
2. **jar 哈希精确反查（最强手段，已实测有效）**：若该条目关联了本地 jar，计算 **sha1** 后批量提交 `POST /v2/version_files`，body `{"hashes":[...], "algorithm":"sha1"}`：
   - 命中 → 直接得到 `project_id` **以及用户当前安装的确切版本号**，`match_status="exact"`（来源标 `hash`）。**完全不受文件名被重命名（PCL 格式）影响**，实测重命名前后的哈希反查均 100% 命中。
   - 未命中（返回 `{}`）→ 落到第 3 步。**不得**因为哈希未命中就判定项目不存在（可能未发布在 Modrinth，或文件被改动过）。
   - 实现提示：200 个 jar 的 sha1 应在扫描阶段算好并缓存进 profile（避免每次检查重算），批量 POST 一次搞定。
3. **精确同名（slug 优先）**：用候选名（依次尝试 `mod_id` → jar 内 `name` → 文件名解析出的 `name` → `display_name`）调用 `/v2/search`（`limit=10`，`facets=[["project_type:mod"]]`），按此顺序判定：
   - `normalize(slug) == normalize(N)` 的命中**恰好 1 个** → 自动认定（`exact`）。**即使同时有多个 title 命中，也以唯一的 slug 命中为准。**（实测：搜 `chunky` 时 slug 唯一命中 `chunky`，但 title 还命中 `newbiichunkymod`，此时应直接认定 `chunky`。）
   - 否则 `normalize(title) == normalize(N)` 的命中**恰好 1 个** → 自动认定（`exact`）。
   - 否则（0 个或多个）→ 进入交互选择。
4. **无精确同名** → **必须告警 + 交互**（用户明确要求：「找不到名称完全一致的模组的时候，弹出这个警告和交互」）：
   - 打印 ⚠️：`未找到与「<名字>」完全同名的项目`
   - 列出 top 5 候选：序号、`title`、`slug`、下载量、一句话简介
   - 选项：`1..5` 选择 ｜ `m` 手动输入 slug 或项目 URL ｜ `s` 本次跳过（标 ⚪ UNMATCHED）｜ `i` 永久忽略（写 `match_status="ignored"`）｜ `q` 退出
   - 选定后 `match_status="manual"` 并写回 profile
5. **非交互模式**（`--yes` 或 stdin 非 TTY）→ **绝不猜**：标 ⚪ `UNMATCHED`，报告末尾汇总「N 个模组未能自动匹配，请交互运行确认」。
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
- `POST https://api.modrinth.com/v2/version_files`，body `{"hashes": ["<sha1>", ...], "algorithm": "sha1"}` → 返回 `{sha1: VersionInfo}`；未命中的哈希不出现在返回里（实测**不报错、返回 `{}`**）
- ⚠️ `/project/{id}/version` 的返回顺序**已按发布时间倒序**，直接信任该顺序
- 关键字段：`slug` `title` `loaders[]` `game_versions[]` `version_number` `date_published` `version_type` `files[].filename/url` `dependencies[]` `project_id`
- 无需 API Key；`User-Agent` 必须标明程序名与版本。

### 9.5 Modrinth 取数策略（**v1.2 实测验证过的最优算法，必须照此实现**）

#### 9.5.1 关键实测数据（决定了架构）

| 事实 | 实测值 | 影响 |
|---|---|---|
| JEI 全量版本数 | **3736 条 / 6.8 MB** | ❌ 全量拉取不可行 |
| JourneyMap 全量 | 1140 条 / 2.2 MB | ❌ |
| 外推 200 模组全量拉取 | **约 326 MB** | ❌ 完全不可接受 |
| `?limit=1` 单条 | **1.1 KB** | ✅ 必须用 limit |
| `?limit` / `?offset` | **支持**（实测生效） | ✅ |
| `?loaders=["fabric"]` | **支持** | ✅ |
| `?game_versions=["26.1"]` | **支持** | ✅ |
| `?version_type=release` | **支持**（实测过滤生效，可服务端筛掉 beta/alpha） | ✅ |
| `/project/{id}/version` 排序 | **严格按 date_published 倒序** | ✅ 直接取首个 |
| `/project/{id}` 的 `versions[]` 字段 | **❌ 不是倒序**（carpet 的前几条是 2022 年的） | ⚠️ **严禁依赖它判断"最新版"** |
| 未命中项目 | HTTP **404 且响应体为空** | ⚠️ 不可直接 `json.loads`，须先判空 |
| 限流响应头 | `X-Ratelimit-Limit: 300` / `X-Ratelimit-Remaining` / `X-Ratelimit-Reset` | ✅ 应读取并据此退避 |

#### 9.5.2 已验证的判定算法（每个模组仅 2 个小请求）

```python
WINDOW = 25           # 单次取多少条，足以覆盖"最近发布的若干条"
L, V = target_loader, target_mc_version

# 请求 A：目标加载器下的最新版本
a = GET(f"/project/{slug}/version",
        loaders=f'["{L}"]', version_type="release", limit=WINDOW)
# 请求 B：目标加载器 + 目标 MC 版本下的最新版本
b = GET(f"/project/{slug}/version",
        game_versions=f'["{V}"]', loaders=f'["{L}"]', version_type="release", limit=WINDOW)
# 请求 B2（仅当 B 为空时）：放宽到 beta/alpha
b2 = GET(f"/project/{slug}/version",
         game_versions=f'["{V}"]', loaders=f'["{L}"]', limit=WINDOW)

latest_loader = a[0] if a else None          # 目标加载器最新正式版
latest_compat = b[0] if b else None          # 目标加载器 + 目标 MC 最新正式版
latest_any    = b2[0] if (not b and b2) else None

if latest_loader is None and not a_any_channels:  -> 🔴 NO_LOADER
elif latest_compat and latest_loader and latest_compat["id"] == latest_loader["id"]:
                                                  -> 🟢 OK
elif latest_compat:                               -> 🟡 OLD_VERSION_ONLY
elif latest_any:                                  -> 🟡 PRERELEASE_ONLY
else:                                             -> 🔴 NO_MC_VERSION
```

> **算法正确性已实测验证**：用该算法对 carpet / journeymap / jei 在 26.1 与 26.3 下判定，**5/5 与全量拉取法的结果完全一致**。
> **成本**：5 次判定共 10 个请求 / 261 KB / 2.68 秒 → 外推 **200 个模组约 400 个请求 / 10.2 MB**，在 6 并发下预计 **30~60 秒**完成，完全可接受。

#### 9.5.3 注意
- `WINDOW` 取值需权衡：太小可能漏掉"最近若干条都是 beta/其他 MC 版本"的情况；25 是实测够用的值，可用 `--window` 暴露给高级用户。
- `version_type` 过滤生效后，请求 B 若返回空且 B2（无 `version_type`）有值 → 说明只有 beta/alpha 支持 → 🟡 `PRERELEASE_ONLY`。
- 缓存层应缓存**精简后的**版本记录（只留 `id/version_number/date_published/version_type/game_versions/loaders/files[].hashes`），实测可把体积压到原始的 **10%**。

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

## 11. 模组识别：jar 元数据 / 哈希 / 文件名（v1.1 **重要修订**）

### 11.1 实测结论（主 Agent 用真实模组验证过，必须据此设计）

| 识别手段 | 实测结果 | 定位 |
|---|---|---|
| **jar 内部 `fabric.mod.json` / `mods.toml` / `neoforge.mods.toml`** | ✅ 稳定拿到 `id`（modid）、`name`、`version`。实测 carpet → `id=carpet`；jei → `id=jei` | **第一优先** |
| **jar 的 sha1 反查 Modrinth** | ✅ 实测 3/3 命中，本地 sha1 与 API 声明完全一致，**重命名成 PCL 格式也照样命中** | **第一优先** |
| **文件名解析** | ❌ **大面积失败**。见 11.2 | **仅兜底** |

### 11.2 文件名解析为什么只能兜底（实测数据，务必告诉用户"低置信度"）

对 14 个真实常见模组文件名跑朴素解析，**只有 3 个得到正确结果**：

| 文件名 | 朴素解析结果 | 是否正确 |
|---|---|---|
| `[地毯] fabric-carpet-26.1+v260402.jar` | name=`carpet` mc=`26.1` ver=`v260402` cn=`地毯` | ✅ |
| `journeymap-1.20.1-5.9.18-fabric.jar` | name=`journeymap` mc=`1.20.1` | ✅ |
| `jei-1.20.1-fabric-15.2.0.27.jar` | name=`jei` mc=`1.20.1` | ✅ |
| `fabric-api-0.92.2+1.20.1.jar` | name=`api-0.92.2` mc=`None` | ❌ |
| `lithium-fabric-0.12.1.jar` | name=`lithium-fabric-0.12.1`（**文件名里根本没有 MC 版本**） | ❌ |
| `ferritecore-6.0.1-fabric.jar` | name=`ferritecore-6.0.1-fabric` | ❌ |
| `chunky-fabric-1.3.146.jar` | 同上 | ❌ |
| `spark-1.10.53-fabric.jar` | 同上 | ❌ |
| `cloth-config-11.1.106-fabric.jar` | 同上 | ❌ |
| `modernfix-fabric-5.19.4+mc1.20.1.jar` | name 里混进了 `5.19.4` | ❌ |
| `sodium-fabric-0.5.8+mc1.20.1.jar` | 同上 | ❌ |
| `servercore-fabric-1.4.6+1.20.1.jar` | mc 被误认成 `1.4.6`（其实是模组版本） | ❌ |
| `c2me-fabric-mc1.20.1-0.2.0+alpha.11.50.jar` | 同上 | ❌ |

**结论（硬性要求）**：
1. **绝不允许**用文件名推断出的 MC 版本作为判定依据 —— 它经常根本不存在或是错的。
2. **绝不允许**用文件名推断出的名字直接搜索后"就近取一个"结果 —— 会把 `lithium-fabric-0.12.1` 搜出空结果。
3. 文件名解析的**唯一合法用途**：当拿不到 jar（用户只粘贴了一份文件名清单）时，尽力产出 ``modid 候选`，并**强制标记为低置信度**（`match_status="guess"`），报告中必须以 ⚠️ 提示"依赖文件名猜测，请人工确认"。

### 11.3 正确的识别流程（按优先级）

```
① 读 jar 内部元数据            → 得到 modid / 展示名 / mod 版本        【高置信】
② 算 jar 的 sha1 批量反查 API  → 得到 project_id / 确切版本号          【高置信】
③ 用 ① 或 ② 得到的名字做精确同名搜索（见第 8 节规则）                  【高置信】
④ 都不行 → 用文件名尽力解析 → 标 match_status="guess"                  【低置信，UI 必须提示】
⑤ 仍不行 → ⚠️ 告警 + 交互选择（或非交互下标 ⚪ UNMATCHED）
```

### 11.4 jar 元数据读取细节

- 候选成员（按优先级）：`fabric.mod.json` → `quilt.mod.json` → `META-INF/neoforge.mods.toml` → `META-INF/mods.toml` → `META-INF/MANIFEST.MF`
- Fabric：取 `id` / `name` / `version` / `depends.minecraft`（可有可无）/ `environment`
- Forge/NeoForge：用 `tomllib` 解析 TOML，取 `[[mods]].modId` / `displayName` / `version`，以及 `[[dependencies.<modid>]]` 里 `modId="minecraft"` 的 `versionRange`
- ⚠️ **实测**：Fabric 模组**不一定**声明 `depends.minecraft`（实测 jei 的 fabric 版就是 `None`）。所以 **jar 内的 MC 版本信息只作提示，不作判定依据**；判定一律以平台返回的 `game_versions` 为准。
- jar 读取必须用 `zipfile`，并且**容错**：损坏的 zip、加密条目、超大文件都不能抛异常，只能返回"无元数据"。

### 11.5 文件名解析规则（兜底路径，尽力而为）

- **PCL 格式**：`[中文名] 服务端名称-游戏版本+模组版本.jar`，实例 `[地毯] fabric-carpet-26.1+v260402.jar`
- **通用格式**：`fabric-carpet-26.1+v260402.jar`
- 处理步骤：去 `.jar` / `.jar.disabled` → 取开头的 `[...]` 作为中文名（可多个，第一个非空为主名，其余进 notes）→ 剩下的部分里用**官方 MC 版本清单**做锚点找 MC 版本 token（不要用正则猜 `\d+\.\d+`）→ 取 `+` 之后为模组版本 → 去掉 `fabric-`/`forge-`/`neoforge-`/`quilt-` 前缀得到名字。
- **必须**把置信度带进结果对象：`confidence: high | low`。

### 11.6 去重合并

- 相同 modid（或相同 sha1）→ 合并为一条；保留全部来源文件名与中文名（`aliases`），`cn_name` 取非空者。
- 同一 modid 的两个不同版本 jar → 合并，但**必须告警**"检测到同一模组存在多个版本文件"，并在 notes 里列出，避免服主漏删导致启动崩溃。

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

---

## 18. 主 Agent 裁决记录（追加决策，优先级同本文档）

| 编号 | 裁决 | 结论 |
|---|---|---|
| D20 | `scan --from-list`（仅文件名的清单导入模式） | ✅ **批准**。理由：功能②的输入不总是"有 jar 的文件夹"，服主常常只拿到一份文件名列表；有它才能让"只有文件名"这条旅程可执行。**约束**：该模式下所有条目 `match_status="guess"`、报告中 modid 前缀 `~`、扫描结果必须显著提示"依赖文件名猜测，请人工核对"；且它只是 `scan` 的一个开关，**不得**放进主菜单首屏，避免诱导用户使用低置信数据源。 |
| D21 | 文档截断的归因 | 实测 `write` 工具写入 126 KB 无损（见 §17.10）。**禁止**以"工具截断"为由改写文档；大文档一律分节写入并即时校验条目数。 |

---

## 17. 附录：主 Agent 实测原始证据（2026-10-01）

供程序员写测试用例时直接引用。

### 17.1 Modrinth 端点实测
| 端点 | 结果 |
|---|---|
| `GET /v2/search?query=<n>&limit=10&facets=[["project_type:mod"]]` | 200。11 个常见 modid 中 **10 个存在 slug 精确同名**；`c2me` 无精确同名（top1 是 `c2me-fabric`）→ 必须走交互 |
| `GET /v2/project/<slug>/version` | 200，**已按发布时间倒序** |
| `POST /v2/version_files` | 200。3/3 命中，返回 `project_id` + `version_number`；未命中哈希**不出现在返回中**且**不报错** |
| `GET /v2/tag/loader` | 200，含 `fabric`/`forge`/`neoforge`/`quilt`/`paper` 等 28 种 |

### 17.2 名字规范化（normalize）实测有效性
`ferritecore` 去掉 `-` 后精确命中了 slug `ferrite-core` → 证明 normalize 规则有效，必须实现。
但 `chunky` 同时 title 命中 `newbiichunkymod` → 证明**必须 slug 优先**（见第 8 节）。

### 17.3 三态判定的真实样例（可直接用作测试断言）
| 模组 | 目标 | 期望状态 | 依据 |
|---|---|---|---|
| carpet | 26.1 / fabric | 🟡 `OLD_VERSION_ONLY` | 最新 fabric 版是 26.3，latest_compat=26.1 |
| carpet | 26.3 / fabric | 🟢 `OK` | latest fabric 版 26.3 支持 26.3 |
| journeymap | 26.3 / fabric | 🟢 `OK`（**若用全局最新会误判为 🟡，这是回归测试重点**） | 存在 `26.3-6.0.9+fabric` |
| jei | 26.1 / fabric | 🟡 `OLD_VERSION_ONLY` | latest_all=31.8.0.49 不支持 26.1；latest_compat=29.34.0.90 |
| jei | 26.3 / fabric | 🟡 `PRERELEASE_ONLY` | release 通道无兼容版本，beta 有 |

### 17.4 官方版本清单
`version_manifest_v2.json`：正式版共 103 条；最近 5 个正式版：`26.3, 26.2, 26.1.2, 26.1.1, 26.1`。**版本号是年份制，绝不能假设 `1.x`。**

### 17.5 终端编码实测
在 PowerShell 控制台直接跑 Python 时，中文输出会因代码页不匹配变成乱码（`�ٷ���ʽ`）。→ 程序**必须**在启动时处理：优先 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`，Windows 上尝试 `SetConsoleOutputCP(65001)`，失败则降级且**不得崩溃**。

### 17.7 请求体积实测（100 次判定的成本基线）
| 取数方式 | HTTP 体积 | 条目数 | 耗时 |
|---|---|---|---|
| `/project/jei/version` 全量 | 6797.6 KB | 3736 | 1.55 s |
| `?loaders=["fabric"]` | 2631.8 KB | 1133 | 0.92 s |
| `?game_versions=["26.1"]&loaders=["fabric"]` | 123.5 KB | 79 | 0.75 s |
| `?limit=1` | **1.1 KB** | 1 | 0.57 s |
| `?loaders=["fabric"]&limit=1` | **1.1 KB** | 1 | 0.61 s |
| 精简后的缓存体（carpet） | 14.6 KB（原始 139.2 KB 的 **10%**） | 134 | — |

### 17.8 `/project/{id}` 的 `versions[]` 顺序反例（务必写进测试）
`carpet` 的 `/project/carpet` 返回 `versions[]` 长度 134，**前 6 个**逐个查 `/version/{id}` 得到：
`1.1.3 (2022-12-29)` → `1.4.8 (2022-12-29)` → `1.4.44 (2022-12-29)` → `1.4.57` → `1.4.69` → `1.4.84`
**即：`versions[]` 是按发布时间升序/创建顺序，绝不是"最新在前"。** 任何"取 `versions[0]` 当最新版"的写法都是 bug。

### 17.9 用 limit 过滤法 vs 全量法的等价性验证（可作为回归测试蓝本）
| 模组 | 目标 | 两个方法的判定结果 | 一致的文案 |
|---|---|---|---|
| carpet | 26.1 / fabric | 🟡 `OLD_VERSION_ONLY` | 最新 fabric 版 26.3 不支持 26.1；最新兼容版 26.1 |
| carpet | 26.3 / fabric | 🟢 `OK` | 最新 fabric 正式版 26.3 支持 26.3 |
| journeymap | 26.3 / fabric | 🟢 `OK` | 最新 fabric 正式版 26.3-6.0.9+fabric 支持 26.3 |
| jei | 26.1 / fabric | 🟡 `OLD_VERSION_ONLY` | 最新 fabric 版 31.8.0.49 不支持 26.1；最新兼容版 29.34.0.90 |
| jei | 26.3 / fabric | 🟡 `PRERELEASE_ONLY` | 仅测试版可用：31.8.0.49 (beta) |
**5/5 完全一致。**

### 17.10 write 工具容量实测（更正一个误判）
主 Agent 用 126,000 字节的已知内容做写入—回读比对：**文件字节数完全一致，write 工具不存在 50 KiB 截断**。
若某次大文件写入后内容变短，真实原因通常是**生成方（Agent）单次输出的长度上限**，而不是工具。规避办法：大文档分节写入（先 `write` 建骨架，再用 `edit` 逐节追加），并在写完立即用行数/条目数校验。

### 17.6 jar 元数据实测样例
| 文件 | 元数据 | 关键字段 |
|---|---|---|
| `fabric-carpet-26.3+v260915.jar` | `fabric.mod.json` | `id="carpet"`, `name="Carpet Mod"`, `version="26.3+v260915"`, `depends.minecraft=">=26.3"` |
| `jei-26.3-fabric-31.8.0.49.jar` | `fabric.mod.json` | `id="jei"`, `name="Just Enough Items"`, `version="31.8.0.49"`, **`depends.minecraft=None`** ← 证明 MC 依赖不可靠 |
| `jei-26.3-neoforge-31.8.0.49.jar` | `META-INF/neoforge.mods.toml` | `modId="jei"`, `modLoader="javafml"`, `loaderVersion="[4,)"` |
| `jei-1.19.2-forge-11.68.0.1085.jar` | `META-INF/mods.toml` | 同上（旧版 Forge 用此文件名） |

