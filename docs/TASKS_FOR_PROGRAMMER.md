# 程序员任务书 —— Minecraft 模组版本检查工具（modcheck）

> 依据：`docs/PROJECT_BRIEF.md` **v1.2**（唯一事实来源）+ `docs/PRD.md` **v1.1**（产品规格，界面文案以它为准）
> **必读的第二份规范**：`docs/ENGINEERING_CONTRACT.md`（主 Agent 维护的**工程师常驻规范**，与 `PROJECT_BRIEF.md` 同等强制）。它包含：开发环境与沙箱环境变量（`PIP_CACHE_DIR` / `NUITKA_CACHE_DIR` / `TEMP` 必须指向工作区内，否则 pip 与 Nuitka 会失败）、10 条硬性规则、编码规范、测试规范、**Nuitka 打包的实测约束**（必须加 `--assume-yes-for-downloads`；系统 MinGW gcc 8.1.0 会被拒绝，Nuitka 会自动下载 winlibs-gcc 15.2.0 到 `NUITKA_CACHE_DIR`；`Cannot find Windows Runtime DLLs to include` 是无害警告）、以及完成定义（DoD）。
>
> **本任务书 §3 的任务编号是唯一权威**；§2 的里程碑表只表示**依赖顺序**，两者若不一致以 §3 为准。
> 作者：Product Manager 子代理 ｜ 版本 v1.0
> 读者：程序员子代理。**本文件是施工图，按任务号顺序执行。**

---

## 0. 开工前的环境现状（已实测，请照做）

| 项目 | 现状 | 结论 |
|---|---|---|
| 工作目录 | `D:\Programme\python_prgram\mod-version-checker` | 已存在 `pyproject.toml` / `.gitignore` / `docs/` / `.toolchain/` |
| Python 3.11 | `.toolchain\Python311\python.exe` = **3.11.9**，`tomllib`/`ssl`/`sqlite3`/`zipfile` 均可 import | ✅ 直接用它，不要动系统 Python |
| pip | **已可用**：`python -m pip -V` → `pip 24.0` | ✅ |
| pytest | ✅ **已安装**（9.1.1，主 Agent 已装好） | 直接用 |
| nuitka | ✅ **已安装**（4.2.2，主 Agent 已装好） | 直接用 |
| 源码目录 | `src/`、`tests/`、`build/` **都还不存在** | 需要创建 |

**如果依赖缺失才需要安装**（主 Agent 已装好 pytest 9.1.1 与 Nuitka 4.2.2，正常情况**不需要**执行下面这段）：

```
cd /d D:\Programme\python_prgram\mod-version-checker
.toolchain\Python311\python.exe -m pip install --no-warn-script-location pytest nuitka
.toolchain\Python311\python.exe -m pytest --version
.toolchain\Python311\python.exe -m nuitka --version
```

**跑测试的统一命令**（写进 README 与 CI 说明）：

```
.toolchain\Python311\python.exe -m pytest tests -m "not live"      :: Windows
.toolchain/Python311/python.exe -m pytest tests -m "not live"      # Linux
```

**运行程序的统一命令**（PM 验收时会直接用它）：

```
:: Windows：仓库根目录下提供 modcheck.cmd
modcheck.cmd --help
modcheck.cmd check --profile demo --mc 26.3 --loader fabric --no-color
```

`modcheck.cmd`（必须创建，P0；Linux 对应 `modcheck.sh`）：

```
@echo off
setlocal
set "ROOT=%~dp0"
if defined MODCHECK_PYTHON (set "PY=%MODCHECK_PYTHON%") else if exist "%ROOT%.toolchain\Python311\python.exe" (set "PY=%ROOT%.toolchain\Python311\python.exe") else (set "PY=python")
set "PYTHONPATH=%ROOT%src"
"%PY%" -m modcheck %*
```

---

## 1. 全局编码约定（违反即返工）

1. **Python 3.11 语法基线**。禁止 3.12+ 语法（PEP 695 `type` 语句、`itertools.batched` 等）。可用 `match`、`X | None`、`tomllib`、`dataclass(slots=True)`、`StrEnum` 的替代（用 `class X(str, Enum)`，3.11 已有 `StrEnum` 但统一用 `(str, Enum)` 更稳）。
2. **零第三方运行时依赖**。只用标准库。`pytest` 只出现在 `[project.optional-dependencies].dev`，绝不 import 进 `src/`。
3. **core 纯净**：`modcheck/core/**` 与 `modcheck/storage/**` 内**禁止** `print` / `input` / `sys.exit` / 直接写 `sys.stdout` / `sys.stderr`。所有展示交给 `cli/`。core 允许读文件（jar、fixture），但不允许联网——联网只经注入的 Provider。
4. **异常分层**：所有领域异常定义在 `modcheck/errors.py`；`ProviderError` 及其子类也定义在那里，但**只由 `providers/http.py` 抛出**（满足基线 §9.1「只抛 ProviderError 的子类」与「core 只捕获领域异常」两条）。
5. **文案零散落**：所有用户可见字符串必须在 `modcheck/i18n.py`，其它模块只允许调用 `t("key", ...)`。**PRD §5 的文案是逐字合同**，照抄。
6. **路径与编码**：一律 `pathlib.Path`；一切 `open()` 显式 `encoding="utf-8"`；写 JSON 用 `ensure_ascii=False, indent=2` + UTF-8 无 BOM。
7. **原子写**：任何写配置/缓存/清单都必须「先写 `<name>.tmp` → `os.replace`」。
8. **类型注解**：公开函数必须有完整注解；`py.typed` 已在 `pyproject.toml` 声明，请创建空文件 `src/modcheck/py.typed`。
9. **docstring**：每个模块一个中文 docstring 说明职责；每个公开函数一句中文说明。
10. **不许裸 except**：`except Exception` 只允许出现在「单个模组隔离」「jar 读取」「顶层兜底」三处，且必须记录到 `ReportItem.message` 或日志字符串。

---

## 2. 实现顺序（里程碑）

| 里程碑 | 内容 | 任务号 | 完成判据 |
|---|---|---|---|
| **M0 骨架** | 包结构、errors、i18n 空壳、console、main 骨架、modcheck.cmd | **T-01, T-02, T-03, T-16, T-17** | `modcheck.cmd --version` 与 `--help` 能跑 |
| **M1 纯逻辑**（P0，先行） | models / mcversion / filename / jarmeta+hashid / matching | **T-04, T-05, T-06, T-07, T-08** | 上述 core 单测全绿（含基线 §11.2 的 14 条文件名样例） |
| **M2 判别核心** | `classify()` 纯函数 + 报告数据结构 | **T-09, T-10** | `classify` 六分支 + 基线 §17.3 的 5 条真实断言全绿 |
| **M3 取数** | http（限速/退避/缓存） / modrinth（limit 法 + version_files） / mojang / curseforge 占位 / registry / cache | **T-11, T-12, T-13, T-14** | 假 HttpClient 单测全绿；`-m live` 能查到 carpet |
| **M4 存储与扫描** | paths / settings / profiles / scan 命令 | **T-15, T-20, T-19（scan 部分）** | `scan` 能对 fixture 目录生成清单 |
| **M5 检查与报告**（P0 收口） | checker 编排 / 渲染 / check 命令 / 退出码 / 导出 / 测试 | **T-18, T-19（check 部分）, T-23** | `check --profile demo ...` 输出与 PRD §5.3 一致 |
| **M6 交互** | menu / prompts / 匹配交互全流程 | **T-21** | 无参数启动可走完一条完整路径 |
| **M7 打包与收尾** | Nuitka 打包（standalone 默认）、README、覆盖率收尾 | **T-22, T-24, T-23（覆盖率）** | `dist/modcheck/modcheck.exe` 能跑；core 覆盖率 ≥ 80% |

**M1/M2 之前不要碰网络代码**：`classify` 的 6 个分支和 brief §17.3 的 5 条真实断言必须先绿。

---

## 3. 任务清单

> 每个任务格式：**目标 / 输入 / 输出（签名级契约）/ 依赖 / 验收 / 必须的单测**

### T-01 包骨架与元信息

- **目标**：建立 `src/modcheck/` 完整目录树，`python -m modcheck` 可运行。
- **输出**：
  ```python
  # src/modcheck/__init__.py
  __version__: str = "0.1.0"
  APP_NAME: str = "modcheck"
  APP_TITLE: str = "Minecraft 模组版本检查工具"
  # src/modcheck/__main__.py
  from modcheck.cli.main import main
  if __name__ == "__main__": raise SystemExit(main())
  ```
- **依赖**：无
- **验收**：`modcheck.cmd --version` 打印 `modcheck 0.1.0`；`modcheck.cmd --help` 打印中文帮助且不联网、≤ 2 秒。
- **单测**：`tests/test_smoke.py::test_version`

### T-02 `errors.py`（领域异常）

- **目标**：全部异常一处定义，每条自带中文可读信息与退出码。
- **输出**：
  ```python
  EXIT_OK=0; EXIT_BLOCKED=1; EXIT_UNKNOWN=2; EXIT_USAGE=3; EXIT_NO_SOURCE=4; EXIT_INTERRUPTED=130

  class ModcheckError(Exception):
      exit_code: int = 1
      def __init__(self, message: str, *, hint: str = "", code: str = "") -> None: ...
      @property
      def message(self) -> str: ...
      @property
      def hint(self) -> str: ...

  class ConfigError(ModcheckError):        exit_code = EXIT_USAGE
  class ProfileError(ModcheckError):       exit_code = EXIT_USAGE
  class JarReadError(ModcheckError):       exit_code = EXIT_OK   # 单文件问题，不致命
  class UserCancelled(ModcheckError):      exit_code = EXIT_INTERRUPTED

  class ProviderError(ModcheckError):
      retryable: bool = False
  class ProviderUnavailable(ProviderError):  exit_code = EXIT_NO_SOURCE
  class ProviderNetworkError(ProviderError): retryable = True
  class ProviderHTTPError(ProviderError):
      def __init__(self, message, *, status: int, url: str, hint: str = "") -> None: ...
  class ProviderRateLimited(ProviderHTTPError): retryable = True
  class ProviderNotFound(ProviderError): ...
  class ProviderParseError(ProviderError): ...
  ```
- **依赖**：无
- **验收**：`exit_code` 与 PRD §5.10 的错误表一致。
- **单测**：异常继承关系与 `exit_code` 断言。

### T-03 `i18n.py`（文案集中）

- **目标**：PRD §5 的每一条文案都能通过 `t(key, **kw)` 取到；不得在别处写死中文。
- **输出**：
  ```python
  def t(key: str, /, **kw: object) -> str: ...          # 缺失 key → 返回 "«key»" 并写 stderr 一次（开发期暴露）
  def tn(key: str, n: int, /, **kw: object) -> str: ... # 复数/量词：中文直接返回 t(key, n=n)
  def has(key: str) -> bool: ...
  ```
  **必须存在的 key（节选，命名规范 `域.子域.名`）**：
  `app.title` `menu.title` `menu.item.check` … `menu.item.quit` `menu.hint.no_profile`
  `report.header.title` `report.header.profile` `report.header.target` `report.header.sources`
  `report.header.origin` `report.header.time` `report.verdict.*`（8 种，见 PRD §5.4）
  `group.blocked.title` `group.degraded.title` `group.unknown.title` `group.ready.title` `group.ignored.title`
  `group.blocked.detail.no_loader` `group.blocked.detail.no_mc_version` `group.blocked.detail.not_found`
  `group.degraded.detail.old_version_only` `group.degraded.detail.prerelease_only`
  `group.unknown.detail.error` `group.unknown.detail.unmatched`
  `report.summary` `report.next.title` `report.next.step1` `report.next.step2` `report.next.step3`
  `report.empty.title` `report.empty.next1` `report.empty.next2`
  `report.origin.guess_note` `report.origin.guess_hint`
  `progress.line.full` `progress.line.mid` `progress.line.min` `progress.line.bar` `progress.done_line`
  `progress.interrupted` `progress.rate_limited`
  `scan.header` `scan.read` `scan.hash` `scan.skipped.header` `scan.skipped.*` `scan.subdir`
  `scan.identify.header` `scan.identify.hash` `scan.identify.meta` `scan.identify.search`
  `scan.dupe.header` `scan.summary` `scan.profile_file`
  `match.warn.title` `match.candidates.header` `match.option.*` `match.manual.prompt` `match.recorded`
  `match.skipped` `match.ignored` `match.noninteractive` `match.summary_hint`
  `err.mc.invalid` `err.mc.snapshot` `err.mc.unknown` `err.loader.unsupported` `err.profile.not_found`
  `err.profile.exists` `err.profile.corrupt` `err.profile.schema` `err.dir.not_found` `err.profile.empty_dir`
  `err.export.failed` `err.source.none` `err.net.offline` `err.http.5xx` `err.rate_limited` `err.timeout`
  `err.parse.provider` `err.cert` `err.hash.miss`
  `warn.config.not_writable` `warn.cache.not_writable` `warn.encoding.failed` `warn.dupe_modid`
  `warn.mojang_unavailable` `warn.guess_count`
  `profile.list.header` `profile.show.header` `versions.header` `config.show.header` `cache.info.header`

**PRD §5.10 的 E01~E28 必须与本表的 key 一一对应（漏一条，程序员就会自己造文案）**：

| 错误编号 | 必须存在的 key | 说明 |
|---|---|---|
| E01 | `err.net.offline` + `err.net.offline.hint` | 断网（含代理提示） |
| E02 | `group.unknown.detail.timeout` + `group.unknown.hint.timeout` | 单模组超时（报告内） |
| E03 | `err.rate_limited` + `group.unknown.detail.rate_limited` + `group.unknown.hint.rate_limited` | 429 |
| E04 | `group.unknown.detail.http_5xx` + `group.unknown.hint.http_5xx` | 5xx |
| E05 | `group.blocked.detail.not_found` + `group.blocked.hint.not_found` | 项目不存在 |
| E06 | `info.project.renamed` | 项目改名已自动更新 |
| E07 | `err.mc.invalid` | 版本号格式错 |
| E08 | `err.mc.snapshot` | 快照版本 |
| E09 | `err.mc.unknown` | 官方清单里没有 |
| E10 | `err.loader.unsupported` | 加载器不支持 |
| E11 | `err.profile.corrupt` | 清单 JSON 损坏 |
| E12 | `err.profile.schema` | 缺 mods 字段 |
| E13 | `scan.skipped.broken` + `group.unknown.detail.jar_unreadable` | jar 读不了 |
| E14 | `report.verdict.all_blocked` + `report.verdict.all_blocked.tip` | 全部阻塞 |
| E15 | `report.empty.title` + `report.empty.next1` + `report.empty.next2` | 空清单 |
| E16 | `progress.interrupted` + `progress.interrupted.hint` | Ctrl+C |
| E17 | `warn.config.not_writable` | 配置目录只读 |
| E18 | —（重定向无文案） | — |
| E19 | `debug.color.disabled` | 仅 `--debug` |
| E20 | `err.source.none` | 无可用数据源 |
| E21 | —（缓存坏数据无文案） | — |
| E22 | `err.export.failed` | 导出失败 |
| E23 | `debug.jobs.clamped` | 仅 `--debug` |
| E24 | `warn.merge_modid` | 载入时合并 |
| E25 | `err.hash.miss` | 指纹未命中 |
| E26 | `group.blocked.detail.no_loader` + `group.blocked.hint.no_loader` | 没有该加载器 |
| E27 | `warn.encoding.failed` | 编码设置失败 |
| E28 | `group.blocked.detail.no_files` + `group.blocked.hint.no_files` | 项目没有任何文件 |

**审计补充的必备 key**（v1.1 自洽审计发现，PRD §11）：`err.from_list.missing`、`warn.rate_limited_slow`、`warn.dupe_modid`、`info.large_profile`、`debug.window.small`、`progress.tick`（非 TTY 每 20% 一行）、`report.ready_hint`（就绪组 > 30 时的提示）、`report.quiet.ready_omitted`（`--quiet` 下就绪组的折叠行）、`scan.identify.filename`。

**命名铁律**：每一个 `reason_code` 都必须有**成对**的 key —— `group.<组>.detail.<code>`（原因行）与 `group.<组>.hint.<code>`（建议行）；每个分组都必须有 `group.<status>.title` 与 `group.<status>.desc`（标题 + 说明句）。缺任何一半都算未完成。
- **依赖**：无
- **验收**：随机抽 10 个 key 与 PRD §5 逐字比对一致（含全角标点与空格）。
- **单测**：`tests/test_i18n.py`：所有 key 存在、格式化不抛异常、文案里不含未替换的 `{`。

### T-04 `core/models.py`（数据模型，纯数据）

- **目标**：PRD §0.1/§4.4 的全部模型，可 JSON 双向序列化。
- **输出**：
  ```python
  class Loader(str, Enum):
      FABRIC="fabric"; NEOFORGE="neoforge"; FORGE="forge"
      @property
      def display_name(self) -> str: ...        # "Fabric"/"NeoForge"/"Forge"
      @classmethod
      def parse(cls, raw: str) -> "Loader": ... # 大小写不敏感；非法 → ConfigError(t("err.loader.unsupported"))

  class Status(str, Enum):   READY="ready"; DEGRADED="degraded"; BLOCKED="blocked"; UNKNOWN="unknown"; IGNORED="ignored"
  class ReasonCode(str, Enum):
      OK="OK"; OLD_VERSION_ONLY="OLD_VERSION_ONLY"; PRERELEASE_ONLY="PRERELEASE_ONLY"
      NO_LOADER="NO_LOADER"; NO_MC_VERSION="NO_MC_VERSION"; NOT_FOUND="NOT_FOUND"
      NO_FILES="NO_FILES"          # 项目存在但一个文件都没有（独立码，不复用 NO_LOADER）
      ERROR="ERROR"; UNMATCHED="UNMATCHED"; IGNORED="IGNORED"; MC_VERSION_FUZZY="MC_VERSION_FUZZY"
  class MatchStatus(str, Enum):
      EXACT="exact"; MANUAL="manual"; UNMATCHED="unmatched"; IGNORED="ignored"; GUESS="guess"
  class SourceKind(str, Enum):
      HASH="hash"; JAR_META="jar_meta"; SEARCH="search"; FILENAME="filename"
      @property
      def display(self) -> str: ...   # "文件指纹" / "jar 内信息" / "名称搜索" / "文件名猜测"

  @dataclass(frozen=True, slots=True)
  class FileInfo:
      filename: str; url: str; primary: bool; size: int; hashes: dict[str, str]

  @dataclass(frozen=True, slots=True)
  class VersionInfo:
      version_id: str; version_number: str; name: str; project_id: str
      date_published: str                      # 原样保存 ISO 字符串，禁止自行解析排序
      version_type: str                        # release | beta | alpha
      game_versions: tuple[str, ...]; loaders: tuple[str, ...]
      files: tuple[FileInfo, ...]
      @property
      def is_release(self) -> bool: ...
      @property
      def primary_file(self) -> FileInfo | None: ...   # primary==True 者，否则 files[0]
      @classmethod
      def from_api(cls, raw: dict) -> "VersionInfo": ...
      def to_cache(self) -> dict: ...                  # 精简：只留必要字段（体积 ≤ 15%）
      @classmethod
      def from_cache(cls, raw: dict) -> "VersionInfo": ...

  @dataclass(frozen=True, slots=True)
  class ProjectHit:
      project_id: str; slug: str; title: str; downloads: int; description: str; provider: str
  @dataclass(frozen=True, slots=True)
  class ProjectInfo:
      project_id: str; slug: str; title: str; description: str; project_type: str
      loaders: tuple[str, ...]; game_versions: tuple[str, ...]; downloads: int
      version_count: int        # len(versions[])，**只用于区分 NO_FILES / NO_LOADER**，绝不用于判断最新版

  @dataclass(slots=True)
  class Detected:
      mc_versions: list[str] = field(default_factory=list)   # 仅提示，绝不参与判定
      loaders: list[str] = field(default_factory=list)
      mod_version: str | None = None

  @dataclass(slots=True)
  class ModEntry:
      key: str; display_name: str; cn_name: str | None = None; mod_id: str | None = None
      file_name: str | None = None; sha1: str | None = None
      aliases: list[str] = field(default_factory=list)       # 全部来源文件名 + 其它中文名
      sources: dict[str, str | None] = field(default_factory=dict)   # {"modrinth": slug, "curseforge": None}
      detected: Detected = field(default_factory=Detected)
      match_status: MatchStatus = MatchStatus.UNMATCHED
      source_kind: SourceKind | None = None
      current_version: str | None = None                     # 高置信"你当前版本"（决策 D17）
      notes: str = ""; added_at: str = ""; updated_at: str = ""
      @property
      def best_name(self) -> str: ...       # cn_name or display_name or mod_id or key
      def search_candidates(self) -> list[str]: ...   # mod_id → jar name → 文件名候选 → display_name，去重保序

  @dataclass(slots=True)
  class Profile:
      schema_version: int = 1; name: str = ""; description: str = ""
      created_at: str = ""; updated_at: str = ""; mods: list[ModEntry] = field(default_factory=list)

  @dataclass(slots=True)
  class Settings:
      schema_version: int = 1; default_mc_version: str | None = None; default_loader: Loader = Loader.FABRIC
      color: str = "auto"; proxy: str | None = None; concurrency: int = 6
      timeout_seconds: float = 20.0; retries: int = 3
      cache_ttl_hours: dict[str, float] = field(default_factory=lambda: {"mojang": 24.0, "api": 6.0})
      providers: dict[str, dict] = field(default_factory=...)
  ```
- **依赖**：T-02, T-03
- **验收**：`Profile ↔ dict ↔ JSON` 往返完全一致（含中文、`aliases`、`sources`）；未知字段读取时忽略不报错。
- **单测**：`tests/test_models.py`：往返序列化；`Loader.parse("FABRIC")`；`Loader.parse("quilt")` 抛 `ConfigError`。

### T-05 `core/mcversion.py`

- **目标**：年份制与 1.x 制都能识别、比较、取最大；**不用于判定**（判定只做字符串精确包含）。
- **输出**：
  ```python
  RELEASE_RE: Final[re.Pattern[str]]      # ^\d+\.\d+(\.\d+)?$            → 26.3 / 26.1.2 / 1.21.4
  SNAPSHOT_RE: Final[re.Pattern[str]]     # ^(\d{2}w\d{2}[a-z]|\d+\.\d+-(snapshot|pre|rc)\d*)$  (忽略大小写)
  def is_release_like(s: str) -> bool: ...
  def is_snapshot_like(s: str) -> bool: ...
  def version_key(s: str) -> tuple[int, int, int]: ...     # "26.1.2"→(26,1,2)；非法→(-1,-1,-1)
  def compare(a: str, b: str) -> int: ...
  def max_release(versions: Iterable[str]) -> str | None: ...   # 只挑 release 样式，取最大
  def sort_releases(versions: Iterable[str]) -> list[str]: ...  # 降序
  def validate_target_version(v: str, known: Collection[str] | None) -> None:
      """非法 → ConfigError；快照 → ConfigError(t("err.mc.snapshot"))；
         known 非空且 v 不在其中 → ConfigError(t("err.mc.unknown", ...))；known 为空（官方清单没取到）则跳过存在性检查。"""
  ```
- **依赖**：T-02, T-03
- **验收**：`max_release(["1.21.4","26.1","1.21.11","26.3-snapshot-2"]) == "26.3"`；`max_release(["1.21.4","1.21.11"]) == "1.21.11"`（不能按字符串比）。
- **单测**：`tests/test_mcversion.py`：年份制 > 1.x；次版本号 11 > 4；快照不参与；非法输入。

### T-06 `core/filename.py`（**低置信兜底，v1.1 重点修订**）

- **目标**：仅在没有 jar 时兜底；输出必须带候选列表与 `confidence="low"`；**不得用于判定**。
- **输出**：
  ```python
  ARCHIVE_SUFFIXES: Final[tuple[str, ...]] = (".jar.disabled", ".jar.old", ".jar.bak", ".zip", ".jar")
  DISABLED_TOKENS: Final[tuple[str, ...]] = (".disabled", ".old", ".bak", ".off")
  LOADER_TOKENS: Final[tuple[str, ...]] = ("fabric", "forge", "neoforge", "quilt", "paper")

  @dataclass(frozen=True, slots=True)
  class ParsedName:
      raw: str
      cn_name: str | None                  # 第一个非空 [...]；其余进 extra_cn_names
      extra_cn_names: tuple[str, ...]
      loader: str | None
      name: str | None                     # 最可能的名字
      name_candidates: tuple[str, ...]     # 全部切分候选，最可能的在前（搜索时按顺序试）
      mc_version: str | None               # 仅提示
      mod_version: str | None
      confidence: str = "low"              # 恒为 low（硬性）

  def strip_archive_suffix(filename: str) -> str: ...
  def split_cn_prefix(stem: str) -> tuple[list[str], str]: ...
  def looks_like_mc_version(tok: str, known: Collection[str] | None) -> bool: ...
  def parse_jar_filename(filename: str, *, known_mc_versions: Collection[str] | None = None) -> ParsedName: ...
  def is_archive_like(name: str) -> bool: ...
  def is_disabled_like(name: str) -> bool: ...
  ```
- **算法（必须照此实现）**：
  1. 去后缀（`.jar.disabled` 优先于 `.jar`）。
  2. 取**全部前导** `[...]` 为中文名（第一个为主，其余进 `extra_cn_names`）。
  3. 按 `+` 切成 LHS/RHS：
     - 若 LHS 尾 token 像 MC 版本 → `mc_version = LHS尾`，`mod_version = RHS`（去前导 `v`）；
     - 否则若 RHS 尾 token（先剥 `mc`/`v` 前缀）像 MC 版本 → `mc_version = RHS尾`，`mod_version = LHS尾`；
     - 否则 `mod_version = RHS`，`mc_version = None`。
  4. 剩余 tokens 中，loader 若在**位置 0 或位置 -1** 则剥离。
  5. 在剩余 tokens 里用 `known_mc_versions` **做锚点**找 MC 版本（优先），没有清单时用 `looks_like_mc_version` 启发式（`major ≥ 20`，或 `major == 1 and minor >= 7`）；匹配到就移除。
  6. 若剩余 tokens 的**最后一个**是纯版本样式（`^\d+(\.\d+)*([-+].*)?$` 或含 alpha/beta/rc）→ 并入 `mod_version`。
  7. 剩下的 join 成 `name`；同时产出 `name_candidates` = [剥离 loader 的结果, 不剥离 loader 的完整形态]（去重、去掉空串、最可能的在前）。
- **必须通过的 14 条真实样例**（基线 §11.2，逐条进单测）：

| 文件名 | 期望 |
|---|---|
| `[地毯] fabric-carpet-26.1+v260402.jar` | cn=`地毯`, loader=`fabric`, name=`carpet`, mc=`26.1`, mod=`v260402` |
| `fabric-carpet-26.1+v260402.jar` | name=`carpet`, mc=`26.1`, mod=`v260402` |
| `journeymap-1.20.1-5.9.18-fabric.jar` | name=`journeymap`, mc=`1.20.1`, mod=`5.9.18` |
| `jei-1.20.1-fabric-15.2.0.27.jar` | name=`jei`, mc=`1.20.1`, mod=`15.2.0.27` |
| `fabric-api-0.92.2+1.20.1.jar` | mc=`1.20.1`（**绝不能是 0.92.2**）, `"fabric-api" in name_candidates` |
| `modernfix-fabric-5.19.4+mc1.20.1.jar` | mc=`1.20.1`, mod=`5.19.4`, name=`modernfix` |
| `sodium-fabric-0.5.8+mc1.20.1.jar` | mc=`1.20.1`, name=`sodium` |
| `servercore-fabric-1.4.6+1.20.1.jar` | mc=`1.20.1`（**绝不能是 1.4.6**）, name=`servercore` |
| `c2me-fabric-mc1.20.1-0.2.0+alpha.11.50.jar` | mc=`1.20.1`, name=`c2me` |
| `lithium-fabric-0.12.1.jar` | name=`lithium`, mc is None |
| `ferritecore-6.0.1-fabric.jar` | name=`ferritecore`, mod=`6.0.1` |
| `chunky-fabric-1.3.146.jar` | name=`chunky` |
| `spark-1.10.53-fabric.jar` | name=`spark` |
| `cloth-config-11.1.106-fabric.jar` | name=`cloth-config` |

- **依赖**：T-02, T-05
- **验收**：上表 14 条全绿，且所有结果的 `confidence == "low"`。
- **单测**：`tests/test_filename.py`（上表 + 空名/纯中文名/无扩展名/`.jar.disabled`）。

### T-07 `core/jarmeta.py` + `core/hashid.py`（**第一优先识别手段**）

- **目标**：读 jar 内部元数据 + 算 sha1；**永不抛异常**。
- **输出**：
  ```python
  # core/jarmeta.py
  MAX_MEMBER_BYTES: Final[int] = 2 * 1024 * 1024
  MEMBER_PRIORITY: Final[tuple[str, ...]] = (
      "fabric.mod.json", "quilt.mod.json",
      "META-INF/neoforge.mods.toml", "META-INF/mods.toml", "META-INF/MANIFEST.MF")

  @dataclass(frozen=True, slots=True)
  class JarMeta:
      path: Path; mod_id: str | None; name: str | None; version: str | None
      loader_hint: str | None            # fabric|quilt|forge|neoforge（由命中的成员推断）
      mc_hint: str | None                # 仅提示；Fabric 常常是 None（实测 jei 就是）
      depends: dict[str, list[str]]
      source_member: str | None
      error: str | None                  # 人类可读失败原因；None 表示成功

  def read_jar_meta(path: Path) -> JarMeta: ...        # 任何异常都吞掉并写进 error
  def parse_fabric_json(raw: bytes) -> tuple[str | None, str | None, str | None, dict[str, list[str]], str | None]: ...
  def parse_mods_toml(raw: bytes) -> tuple[str | None, str | None, str | None, dict[str, list[str]], str | None]: ...

  # core/hashid.py
  def sha1_of_file(path: Path, *, chunk: int = 65536) -> str: ...   # 流式；大文件不爆内存
  def is_probably_jar(path: Path) -> bool: ...                     # 扩展名 + 前 2 字节 PK
  ```
- **细节**：
  - Fabric：`id` / `name` / `version`；`depends.minecraft` 可能是 str 或 list 或 **缺失**（实测 jei 为 `None`）→ 只作 `mc_hint`。
  - Forge/NeoForge：`tomllib.loads` → `[[mods]].modId/displayName/version`；`[[dependencies.<modid>]]` 里 `modId=="minecraft"` 的 `versionRange` 取左界作为 `mc_hint`（如 `[1.20.1,1.21)` → `1.20.1`）。
  - ⚠️ **实测**：Forge 系 jar 的 toml 里 `versionRange` 常带 `[` `)`，解析失败时返回 `None` 而不是猜。
- **依赖**：T-02
- **验收**：对 `tests/fixtures/jars/*.jar`（现场用 `zipfile` 生成）全部返回正确 modid；对 `broken.jar`（100 字节垃圾）返回 `error != None` 且**不抛异常**；对无元数据 zip 返回全 None。
- **单测**：`tests/test_jarmeta.py`（含 fabric / quilt / neoforge toml / forge toml / MANIFEST 兜底 / 损坏 / 超大条目）。

### T-08 `core/matching.py`（**slug 优先**）

- **目标**：决策 A4 的纯逻辑实现。
- **输出**：
  ```python
  def normalize(s: str) -> str: ...          # lower + 删除 - _ 空格 .
  def candidate_names(entry: ModEntry) -> list[str]: ...    # 依次 mod_id → jar name → 文件名候选 → display_name
  @dataclass(frozen=True, slots=True)
  class MatchResult:
      hit: ProjectHit | None
      how: str            # "slug" | "title" | "none"
      ambiguous: bool
  def match_exact(hits: Sequence[ProjectHit], candidates: Sequence[str]) -> MatchResult: ...
  def rank_candidates(hits: Sequence[ProjectHit], candidates: Sequence[str]) -> list[ProjectHit]: ...
      # 仅用于交互列表排序：完全同名 → 前缀匹配 → 下载量降序
  def format_downloads(n: int) -> str: ...   # 11016662 → "11,016,662"
  ```
- **规则（基线 §8 第 3 步，逐条实现）**：对每个候选 N（按顺序）：
  1. `slug_hits = [h for h in hits if normalize(h.slug) == normalize(N)]`；若 `len == 1` → 命中，`how="slug"`。**即使 title 还命中别的也以此为准**（实测：搜 `chunky` 时 title 还命中 `newbiichunkymod`）。
  2. 否则 `title_hits = [h for h in hits if normalize(h.title) == normalize(N)]`；若 `len == 1` → 命中，`how="title"`。
  3. 否则继续下一个候选；全部候选都不行 → `hit=None, ambiguous=(len(hits)>0)`。
- **依赖**：T-03, T-04
- **验收**：`normalize("ferrite-core") == normalize("ferritecore")`；`normalize("Carpet TIS Addition") != normalize("carpet")`。
- **单测**：`tests/test_matching.py`：真实 fixture `search_carpet.json`（8 条命中）中只有 `carpet` 被认定；`chunky` 场景；`ferritecore → ferrite-core`；全不命中 → 交互。

### T-09 `core/checker.py` —— `classify()`（**本项目的心脏**）

- **目标**：把 PRD §4.3 的 6 个分支写成**纯函数**，可离线单测。
- **输出**：
  ```python
  @dataclass(frozen=True, slots=True)
  class Classification:
      status: Status; reason: ReasonCode
      reason_key: str                     # i18n 文案 key（详情行「原因」）
      hint_key: str                       # i18n 文案 key（详情行「建议」）
      latest_for_loader: VersionInfo | None
      latest_compat: VersionInfo | None
      latest_any: VersionInfo | None
      max_supported_mc: str | None
      available_loaders: tuple[str, ...]  # 供 NO_LOADER 文案使用

  def classify(*, loader: Loader, mc_version: str,
               releases_for_loader: Sequence[VersionInfo],   # 请求 A
               compat_releases: Sequence[VersionInfo],       # 请求 B
               compat_any: Sequence[VersionInfo],            # 请求 B2（可为空）
               any_for_loader: Sequence[VersionInfo],        # 请求 A2（可为空）
               prerelease: bool = False) -> Classification: ...
  ```
- **判定顺序（严格照抄 PRD §4.3）**：
  ```
  ① A 空 且 A2 空            → BLOCKED / NO_LOADER（available_loaders 由调用方补）
  ①b A 空 且 A2 空 且 project.version_count == 0 → 🔴 NO_FILES（项目已没有任何文件，独立码）
  ② A 空 但 A2 非空          → 继续 ④⑤
  ③ B 非空 且 B[0].id == A[0].id → READY / OK
  ④ B 非空                   → DEGRADED / OLD_VERSION_ONLY（latest_compat = B[0]）
  ⑤ B 空 且 B2 非空          → DEGRADED / PRERELEASE_ONLY（latest_any = B2[0]）
  ⑥ 其余                     → BLOCKED / NO_MC_VERSION
                                （max_supported_mc = max_release(∪ A[i].game_versions)）
  注：prerelease=True 时 A/B 已经是不过滤通道的列表，不会再走到 ⑤。
  ```
- **绝对禁止**：任何形式的自行排序（不得 `sorted(..., key=date_published)`、不得取 `max()`）。**只准取数组第一个元素**（基线 §7：API 已倒序，日期会并列）。
- **依赖**：T-04, T-05
- **验收**：基线 §17.3 的 5 条真实断言全绿 + 六个分支各有覆盖。
- **单测**：`tests/test_classify.py`（见 §4.2 必含用例 6~13）。

### T-10 `core/report.py`（报告数据结构 + 结论）

- **目标**：报告是纯数据；渲染交给 `cli/render.py`（见 T-19）。
- **输出**：
  ```python
  GROUP_ORDER: Final[tuple[Status, ...]] = (Status.BLOCKED, Status.DEGRADED, Status.UNKNOWN, Status.READY, Status.IGNORED)

  class Verdict(str, Enum):
      ALL_READY="all_ready"; READY_WITH_DEGRADED="ready_with_degraded"; BLOCKED="blocked"
      INCOMPLETE="incomplete"; ALL_UNKNOWN="all_unknown"; ALL_BLOCKED="all_blocked"
      EMPTY="empty"; INTERRUPTED="interrupted"

  @dataclass(slots=True)
  class ReportItem:
      mod: ModEntry; status: Status; reason: ReasonCode
      reason_key: str; hint_key: str
      latest_for_loader: VersionInfo | None = None
      latest_compat: VersionInfo | None = None
      latest_any: VersionInfo | None = None
      max_supported_mc: str | None = None
      available_loaders: tuple[str, ...] = ()
      current_version: str | None = None
      provider_message: str = ""          # 详情行里可直接展示的动态补充（如超时原因）

  @dataclass(slots=True)
  class Report:
      mc_version: str; loader: Loader; profile_name: str
      generated_at: str; elapsed: float = 0.0
      groups: dict[Status, list[ReportItem]] = field(default_factory=...)
      warnings: list[str] = field(default_factory=list)
      source_stats: dict[SourceKind, int] = field(default_factory=...)
      requests_made: int = 0; cache_hits: int = 0
      interrupted: bool = False; completed: int = 0; total: int = 0
      @property
      def summary(self) -> dict[str, int]: ...
          # 必须返回：{"total_all", "total_checked", "ready", "degraded", "blocked", "unknown", "ignored"}
          # 恒等式（在 to_dict() 与渲染前各断言一次，assert 失败即编程错误）：
          #   ① ready + degraded + blocked + unknown == total_checked
          #   ② total_checked + ignored == total_all
          # total_all  = len(profile.mods)
          # total_checked = total_all - ignored
          # 报告头的（N 个模组）用 total_all；结论行的「{n} 个模组」用 total_checked
      def verdict(self) -> Verdict: ...
      def to_dict(self) -> dict: ...                # {"schema_version": 1, ...} 供 JSON 导出与未来 GUI
      def iter_items(self) -> Iterator[ReportItem]: ...
  def build_action_hints(report: Report) -> list[str]: ...   # PRD §5.4「下一步」的文本行
  def origin_line(report: Report) -> str: ...
  ```
- **依赖**：T-04, T-08(classify 结果)
- **验收**：`verdict()` 覆盖 PRD §5.4 的 8 种结论；`summary["total"]` 不含 ignored。
- **单测**：`tests/test_report.py`：8 种 verdict；空报告；全 ignored。

### T-11 `providers/http.py`（限速 / 退避 / 缓存 / 统计）

- **目标**：唯一出网口；可注入 `clock`/`sleep` 以便离线单测。
- **输出**：
  ```python
  @dataclass(slots=True)
  class HttpConfig:
      timeout: float = 20.0; retries: int = 3
      backoff: tuple[float, ...] = (0.5, 1.0, 2.0)
      proxy: str | None = None
      user_agent: str = f"modcheck/{__version__} (+https://github.com/)"
      rate_limit_per_min: int = 250          # 官方 300，留 20% 余量。**这是 S1（200 模组首次 ≤150 秒）的推导依据，不得为提高速度擅自调高**
      window: int = 25

  class RateLimiter:
      def __init__(self, per_minute: int, *, clock: Callable[[], float] = time.monotonic,
                   sleep: Callable[[float], None] = time.sleep) -> None: ...
      def acquire(self) -> None: ...                      # 线程安全令牌桶
      def pause(self, seconds: float) -> None: ...        # 429 时全局暂停

  class HttpClient:
      def __init__(self, cfg: HttpConfig, *, cache: "HttpCache | None" = None,
                   limiter: RateLimiter | None = None,
                   clock: Callable[[], float] = time.monotonic,
                   sleep: Callable[[float], None] = time.sleep) -> None: ...
      def get_json(self, url: str, params: Mapping[str, str] | None = None, *,
                   ttl: float | None = None, cache_key: str | None = None) -> Any: ...
      def post_json(self, url: str, payload: Mapping[str, Any], *, ttl: float | None = None) -> Any: ...
      @property
      def stats(self) -> tuple[int, int]: ...             # (requests_made, cache_hits)
  ```
- **行为规则（逐条实现）**：
  1. 缓存命中**不消耗令牌、不发请求**；命中时 `cache_hits += 1`。
  2. 429：读 `Retry-After`（秒）或 `X-Ratelimit-Reset`（相对秒数），`limiter.pause(...)` 后重试；重试次数用尽 → `ProviderRateLimited`。
  3. 5xx：按 `backoff` 退避重试；用尽 → `ProviderHTTPError`。
  4. 网络错误（`URLError`/`socket.timeout`/`TimeoutError`）→ 退避重试；用尽 → `ProviderNetworkError`。
  5. **404：先判响应体是否为空再决定是否 `json.loads`**（基线实测 404 体为空）；抛 `ProviderNotFound`，**不重试**。
  6. 其它 4xx：不重试，抛 `ProviderHTTPError`（附 status 与 url）。
  7. `ssl.SSLCertVerificationError` → `ProviderNetworkError(t("err.cert"))`，不重试。
  8. 响应体上限 32 MB（防御），超限抛 `ProviderParseError`。
  9. `User-Agent` 必须带程序名与版本。
  10. 代理：`urllib.request.ProxyHandler({"http": p, "https": p})`；同时尊重环境变量。
- **依赖**：T-02, T-03, T-16(cache)
- **验收**：注入假 `sleep` 后能断言退避序列为 `[0.5, 1.0, 2.0]`；429 后总耗时 ≥ `Retry-After`；缓存命中时 `requests_made` 不增加。
- **单测**：`tests/test_http.py`（假 opener：200 / 404 空体 / 404 有体 / 429+头 / 500 / 超时 / 证书错误 / 缓存命中 / 缓存损坏）。

### T-12 `providers/base.py` + `providers/modrinth.py`（**limit 过滤法**）

- **目标**：实现基线 §9.5 的 2 请求算法与 §8 的哈希反查。
- **输出**：
  ```python
  # providers/base.py
  class BaseProvider(ABC):
      name: str; display_name: str; available: bool = True
      @abstractmethod
      def search(self, query: str, limit: int = 10) -> list[ProjectHit]: ...
      @abstractmethod
      def get_project(self, project_id: str) -> ProjectInfo | None: ...
      @abstractmethod
      def get_versions(self, project_id: str) -> list[VersionInfo]: ...
      # 以下 4 个有默认实现（基于 get_versions 过滤 + 取首条）→ 假 Provider 只需实现上面 3 个
      def resolve_by_hash(self, sha1s: Sequence[str]) -> dict[str, VersionInfo]: return {}
      def releases_for_loader(self, project_id: str, loader: Loader, *, window: int = 25,
                              prerelease: bool = False) -> list[VersionInfo]: ...
      def compat_releases(self, project_id: str, mc_version: str, loader: Loader, *,
                          window: int = 25, prerelease: bool = False) -> list[VersionInfo]: ...
      def any_for_loader(self, project_id: str, loader: Loader, *, window: int = 25) -> list[VersionInfo]: ...

  # providers/modrinth.py
  class ModrinthProvider(BaseProvider):
      BASE: Final[str] = "https://api.modrinth.com/v2"
      def __init__(self, client: HttpClient) -> None: ...
      # 端点：
      #   GET  /search?query=&limit=10&facets=[["project_type:mod"]]
      #   GET  /project/{slug|id}
      #   GET  /project/{slug|id}/version?<filters>&limit=WINDOW
      #   POST /version_files   body {"hashes":[...], "algorithm":"sha1"}
      @staticmethod
      def _json_array(values: Sequence[str]) -> str: ...   # json.dumps(list, separators=(",",":"))
  ```
- **请求参数编码（易错点）**：`loaders` / `game_versions` 是 **JSON 数组字符串**，必须 `urlencode({"loaders": '["fabric"]'})` → `loaders=%5B%22fabric%22%5D`。**不要**手写 `?loaders=["fabric"]`。
- **三个专用请求（方法签名即契约）**：
  ```python
  def releases_for_loader(project_id, loader, *, window=25, prerelease=False) -> list[VersionInfo]
      # prerelease=False → 追加 version_type=release
  def compat_releases(project_id, mc_version, loader, *, window=25, prerelease=False) -> list[VersionInfo]
      # 追加 game_versions=["V"] + loaders=["L"]（+ version_type=release）
  def any_for_loader(project_id, loader, *, window=25) -> list[VersionInfo]
      # 只加 loaders=["L"]
  ```
- **请求预算（PRD §4.3 / S13 / Z10，必须按此顺序，否则会多花请求）**：

1. 先调 **A**（`releases_for_loader`）。
2. A 非空 → 调 **B**（`compat_releases`）；B 为空 → 再调 **B2**（`prerelease=True`）。最多 3 次。
3. A 为空 → **禁止再调 B**（B ⊆ A，必然为空），直接调 **A2**（`any_for_loader`）；A2 为空 → 再调 1 次 `get_project` 以区分 `NO_FILES` 与 `NO_LOADER`。同样最多 3 次。

**禁止**：为了压低单模组下载体积而降低默认 `window`（默认恒为 25）。`window` 太小会让分支⑥ 的 `max_supported_mc` 不可靠，并使基线 §17.3 的 5 条断言失去依据——预算不够就改预算（PRD §1.3 的方法论条款），不许砍窗口。

**绝对禁止（写进代码注释）**：
  ❌ 使用 `GET /project/{id}` 返回的 `versions[]` 判断"最新版"——基线 §17.8 实测它不是倒序（carpet 前 6 条是 2022 年的）。
  ❌ 对 `/project/{id}/version` 的返回自行排序或取 `max(date_published)`——基线 §7 要求直接信任返回顺序。
  ❌ 全量拉取 `/project/{id}/version`（单模组可达 3736 条 / 6.8 MB）。
- **依赖**：T-04, T-11
- **验收**：`-m live` 测试下 carpet / journeymap / jei 的 5 条断言与基线 §17.9 一致；离线单测用 fixture JSON。
- **单测**：`tests/test_modrinth.py`（URL 构造断言、参数编码断言、404 空体、版本列表取首条）。

### T-13 `providers/mojang.py` + `providers/curseforge.py` + `providers/registry.py`

- **输出**：
  ```python
  # mojang.py
  @dataclass(frozen=True, slots=True)
  class McRelease: version_id: str; release_time: str; type: str
  class MojangVersions:
      def __init__(self, client: HttpClient) -> None: ...
      def list_releases(self, *, limit: int | None = None) -> list[McRelease]: ...   # 只取 type=="release"，按 releaseTime 倒序
      def latest_release(self) -> str | None: ...
      def known_versions(self) -> set[str]: ...    # 供 --mc 校验与文件名锚点

  # curseforge.py —— 占位，见基线 §9.4 的逐条要求
  class CurseForgeProvider(BaseProvider):
      name = "curseforge"; display_name = "CurseForge"; available = False
      # 每个方法都 raise ProviderUnavailable(t("err.cf.no_key"))
      # 模块 docstring 必须写清：x-api-key 头、Key 来源（settings.providers.curseforge.api_key
      #   或环境变量 CURSEFORGE_API_KEY）、端点 /v1/mods/search、/v1/mods/{id}/files、
      #   POST /v1/mods/fingerprints、gameId=432、classId=6、
      #   modLoaderType（1=Forge, 4=Fabric, 6=NeoForge）、MurmurHash2 指纹算法、
      #   以及在 registry 中启用的方法

  # registry.py
  @dataclass(slots=True)
  class ProviderRegistry:
      providers: list[BaseProvider]
      def enabled(self) -> list[BaseProvider]: ...
      def primary(self) -> BaseProvider: ...       # 无可用 → ProviderUnavailable(t("err.source.none"))
      @classmethod
      def from_settings(cls, settings: Settings, client: HttpClient) -> "ProviderRegistry": ...
  ```
- **依赖**：T-04, T-11, T-12
- **验收**：CurseForge 占位**零网络调用**（用假 client 断言调用次数为 0）；`available == False`；界面文案走 PRD §5.2。
- **单测**：`tests/test_registry.py`：默认只有 modrinth；CF 被禁用；CF 方法抛 `ProviderUnavailable`。

### T-14 `cache.py`（TTL + 原子写 + 精简）

- **输出**：
  ```python
  def url_key(url: str) -> str: ...      # sha1(url)，带前缀 "u_"
  @dataclass(frozen=True, slots=True)
  class CacheInfo: files: int; bytes: int; oldest: float | None; newest: float | None
  class HttpCache:
      def __init__(self, root: Path, *, clock: Callable[[], float] = time.time) -> None: ...
      def get(self, key: str, ttl: float) -> Any | None: ...
          # 未命中/TTL 过期/JSON 解析失败 → 返回 None（解析失败时顺手删除坏文件），绝不抛异常
      def put(self, key: str, payload: Any) -> None: ...   # 先写 .tmp 再 os.replace
      def info(self) -> CacheInfo: ...
      def clear(self, *, older_than: float | None = None) -> int: ...
  ```
- **依赖**：T-02
- **验收**：写坏一个缓存文件后 `get` 返回 None 且不抛；并发写同一 key 不产生半截文件。
- **单测**：`tests/test_cache.py`。

### T-15 `storage/paths.py` `settings.py` `profiles.py`

- **输出**：
  ```python
  # paths.py
  def resolve_config_dir(cli_arg: str | None, *, env: Mapping[str, str] = os.environ,
                         exe_dir: Path | None = None) -> Path:
      """优先级：--config-dir > 环境变量 MODCHECK_CONFIG_DIR > 便携目录（exe 同级 config/，可写时）
         > Windows %APPDATA%\modcheck / Linux ~/.config/modcheck。"""
  def is_writable(path: Path) -> bool: ...                 # 真写一个临时文件再删
  def fallback_config_dir() -> Path: ...
  def ensure_config_dir(path: Path) -> tuple[Path, bool]: ...   # (最终目录, 是否发生回退)

  # settings.py
  SETTING_KEYS: Final[tuple[str, ...]] = ("default_mc_version","default_loader","color","proxy",
      "concurrency","timeout_seconds","retries","cache_ttl_hours","providers.curseforge.api_key")
  def load_settings(path: Path) -> Settings: ...     # 缺失→创建默认；损坏→备份为 settings.json.bak-<ts> 并重建（不崩）
  def save_settings(path: Path, s: Settings) -> None: ...
  def set_setting(s: Settings, key: str, raw: str) -> Settings: ...   # 未知名 → ConfigError

  # profiles.py
  def profile_path(dir: Path, name: str) -> Path: ...
  def validate_profile_name(name: str) -> None: ...   # 空/含 \ / : * ? " < > | → ConfigError
  def list_profiles(dir: Path) -> list[ProfileSummary]: ...   # 损坏的清单只跳过并记录，不影响其它
  def load_profile(path: Path) -> Profile: ...        # 损坏 → ProfileError(t("err.profile.corrupt"))
  def save_profile(p: Profile, path: Path) -> None: ...        # 原子
  def new_profile(name: str, description: str = "") -> Profile: ...
  def copy_profile / rename_profile / delete_profile(...) -> None
  def key_of(entry: ModEntry) -> str: ...             # mod_id → "sha1:<sha1>" → normalize(display_name)
  def merge_entries(existing: Sequence[ModEntry], incoming: Sequence[ModEntry]
                    ) -> tuple[list[ModEntry], MergeStats]: ...
  def dedupe_by_key(mods: Sequence[ModEntry]) -> tuple[list[ModEntry], list[str]]: ...
  ```
- **合并规则（决策 D3 + 基线 §11.6）**：key 相同 → 合成一条；`sources` 取非空；`cn_name` 取非空；被合并条目的 `file_name` 与中文名进 `aliases`；`notes` 里追加「已合并：<文件名>」。同 modid 多文件必须产生一条告警文本（返回给调用方展示）。
- **依赖**：T-02, T-03, T-04
- **验收**：损坏 JSON 抛 `ProfileError` 且文案 = PRD E11；`merge_entries` 幂等（合并两次结果相同）。
- **单测**：`tests/test_storage.py`。

### T-16 `console.py`（宽度 / 颜色 / VT / 编码 / 进度条）

- **输出**：
  ```python
  def init_terminal_encoding() -> str:
      """最早调用。① sys.stdout/stderr.reconfigure(encoding='utf-8', errors='replace')
         ② Windows: ctypes.windll.kernel32.SetConsoleOutputCP(65001)（失败忽略）
         返回 'utf-8' 或 'legacy'；任何异常都吞掉，绝不崩（基线 §17.5）。"""
  def enable_windows_vt() -> bool: ...     # SetConsoleMode(ENABLE_VIRTUAL_TERMINAL_PROCESSING)
  def resolve_width(fallback: int = 100) -> int: ...   # 非 TTY 取 COLUMNS 或 100
  def display_width(s: str) -> int: ...    # unicodedata.east_asian_width in ("F","W") → 2
  def truncate(s: str, width: int) -> str: ...
  def pad(s: str, width: int) -> str: ...

  class Console:
      def __init__(self, *, stream: TextIO = sys.stdout, color: str = "auto",
                   width: int | None = None, quiet: bool = False) -> None: ...
      color_enabled: bool; width: int
      def line(self, text: str = "") -> None: ...
      def rule(self, ch: str = "─") -> None: ...
      def group(self, status: Status, title: str) -> None: ...    # 带颜色
      def progress(self, text: str) -> None: ...                  # 原地刷新（\r + 清行）
      def clear_progress(self) -> None: ...
      def flush(self) -> None: ...
  ```
- **颜色规则**：`auto` → `stream.isatty() and not os.environ.get("NO_COLOR")`；Windows 上还需 `enable_windows_vt()` 成功；`--no-color` 强制关。颜色只用 31/32/33/90/1。
- **依赖**：T-03, T-04
- **验收**：`display_width("[地毯] Carpet") == 13`；重定向时 `color_enabled is False`；`init_terminal_encoding()` 在异常环境下不抛。
- **单测**：`tests/test_console.py`（宽度表、截断、NO_COLOR、非 TTY）。

### T-17 `cli/main.py`（argparse 顶层调度 + 退出码）

- **输出**：
  ```python
  def build_parser() -> argparse.ArgumentParser: ...
  def main(argv: Sequence[str] | None = None) -> int: ...
  ```
  **子命令**：`check` / `scan` / `profile` / `versions` / `config` / `cache`；无子命令 → `cli/menu.py`。
  **顶层异常映射**：`KeyboardInterrupt → 130` ｜ `ModcheckError → e.exit_code`（打印 `message` + `hint`）｜ 其它 `Exception → 70`（打印 `t("err.internal")`；仅在 `--debug` 下打印 traceback）。
  **公共参数**：`--config-dir` `--debug` `--version` `--no-color`（check 上另有 `--quiet`）。
  **check 参数**：`--profile` `--file` `--mods-dir` `--mc` `--loader` `--json` `--md` `--csv` `--refresh` `--jobs` `--yes` `--pre` `--quiet` `--window`；`--profile` 与 `--mods-dir` 互斥。
  **scan 参数**：`<DIR> [<DIR>...]`（默认不递归） ｜ `--from-list FILE`（每行一个文件名，仅文件名模式，全部标记为 guess） ｜ `--profile NAME` ｜ `--new` ｜ `--yes`
- **依赖**：T-02, T-03, T-16
- **验收**：`--mc abc` 退出 3 且输出 = PRD E07；`--help` 全中文；无 traceback。
- **单测**：`tests/test_cli_args.py`（参数校验矩阵、退出码）。

### T-18 `cli/render.py`（报告渲染，**排版合同**）

- **目标**：把 `Report` 渲染成 PRD §5.3 的逐字排版。
- **输出**：
  ```python
  def render_report(report: Report, console: Console, *, quiet: bool = False) -> None: ...
  def render_summary(report: Report, console: Console) -> None: ...
  def render_next_steps(report: Report, console: Console) -> None: ...
  def render_version_cell(item: ReportItem) -> str: ...   # §5.3.1 的 "本地 → 最新" 规则
  def column_widths(items: Sequence[ReportItem]) -> tuple[int, int, int]: ...   # (name, modid, version)，全报告统一
  ```
- **硬性规则**：见 PRD §5.3 表格（分隔线、行首、列宽上限 26/20/34、详情行缩进 10、空组不打印、表格内禁用 emoji）。
- **依赖**：T-04, T-10, T-16, T-03
- **验收**：golden 文件逐字节一致（除时间戳与用时行）。
- **单测**：`tests/test_render.py` + `tests/golden/report_26.3_fabric.txt`。

### T-19 `cli/commands/*.py`

- **输出**（每个函数签名 `def run_x(args: argparse.Namespace, ctx: AppContext) -> int`）：
  ```python
  @dataclass
  class AppContext:
      settings: Settings; config_dir: Path; console: Console
      registry: ProviderRegistry; cache: HttpCache; client: HttpClient
      prompter: Prompter; interactive: bool

  def run_check(args, ctx) -> int: ...
  def run_scan(args, ctx) -> int: ...
  def run_profile(args, ctx) -> int: ...
  def run_versions(args, ctx) -> int: ...
  def run_config(args, ctx) -> int: ...
  def run_cache(args, ctx) -> int: ...
  # commands/export.py
  def export_json(report: Report, path: Path) -> None: ...
  def export_markdown(report: Report, path: Path) -> None: ...
  def export_csv(report: Report, path: Path) -> None: ...
  def default_filename(profile_name: str, mc: str, loader: Loader, ext: str,
                       when: datetime | None = None) -> str: ...   # report_服务器A_26.3_fabric_20261001-2103.json
  ```
- **`run_check` 的退出码（优先级从高到低，先命中者胜出）**：

1. 参数 / 配置错误 → **3**
2. 数据源整体不可用（首个请求即失败）→ **4**
3. 用户中断 → **130**
4. 存在 🔴 阻塞项 → **1**（**即使同时存在 ⚪ 未判定，也返回 1** —— 决策 D2 的优先级）
5. 有 ⚪ 且无 🔴 → **2**
6. 其余（全绿或仅 🟡）→ **0**

> 断言用例：§5.3 的样例（3 阻塞 + 2 未判定 + 1 已忽略）必须返回 **1**，不是 2、也不是 130。
- **导出文件路径**：相对路径 → 当前工作目录；写入失败 → `ConfigError(t("err.export.failed", path=...))`（退出 3），但**报告已经在屏幕上输出过**。
- **依赖**：T-10, T-12, T-15, T-17, T-18
- **验收**：`--json` 输出含 `schema_version`、每个 item 的 `reason` 与 `status`；`--md` 可以直接贴到群里。

### T-20 `cli/commands/scan.py` 的实现要点（识别流水线）

**输入形态**：`scan <DIR>`（正常路径）或 `scan --from-list <文件.txt>`（**没有 jar**：跳过 ①②③，直接走 ④⑤，全部条目 `match_status="guess"`、`source_kind=FILENAME`，并在输出里明确告知用户「猜出来的结果请人工核对」）。`--from-list` 模式下不发起 `/version_files` 请求。

```
① 列目录（默认不递归）→ 分类：jar / disabled / 其它
② 对每个 jar：
     m = read_jar_meta(path)          # 永不抛
     h = sha1_of_file(path)           # 边读边算
③ 批量 POST /version_files（每批 ≤ 100 个 sha1；失败不影响主流程）
     命中 → source_kind=HASH, match_status=EXACT, sources.modrinth=slug,
            current_version=version_number, mod_id=项目 slug
④ 未命中的：用 candidate_names（mod_id → jar name → 文件名候选 → display_name）
     逐个做精确同名搜索（T-08 规则）→ 命中即 EXACT / source_kind=SEARCH
⑤ 仍未命中且**没有 jar 元数据** → 文件名兜底 → match_status=GUESS / source_kind=FILENAME
⑥ 同 modid / 同 sha1 多文件 → 合并 + 产生告警文本
⑦ 与已有清单 merge_entries → 原子写盘
⑧ 打印 PRD §5.8 的统计（读入 / 指纹 / 元数据 / 搜索 / 猜测 / 跳过分类 / 重复告警）
```
- **网络失败时**：③ 失败 → 打一行 `⚠ 连不上 Modrinth…` 并继续（退出码仍为 0），仅用 ②④⑤ 生成清单。

### T-21 `cli/menu.py` + `cli/prompts.py`（交互）

- **输出**：
  ```python
  class Prompter:
      def __init__(self, *, input_fn: Callable[[str], str] = input,
                   out: Console | None = None) -> None: ...
      def ask(self, prompt: str) -> str: ...
      def choose(self, title: str, options: Sequence[Choice], *, allow_back: bool = False,
                 default: str | None = None) -> str: ...
      def confirm(self, question: str, *, default: bool = True) -> bool: ...
  class Menu:
      def __init__(self, ctx: AppContext) -> None: ...
      def run(self) -> int: ...      # 主菜单循环；Ctrl+C 在子流程 → 回主菜单；在主菜单 → 返回 130
  ```
- **菜单边界（主 Agent 批复 D20）**：`--from-list`（仅文件名清单模式）**不得出现在主菜单首屏**，它只是 `scan` 的一个开关；主菜单保持 6 个编号项不变。
- **主菜单固定 6 项**：检查 / 扫描 / 管理清单 / 设置 / 版本列表 / 退出（与 PRD §5.2 逐字一致）。
- **交互契约**：每步支持 `b` 返回上一步、`q` 回主菜单（PRD §2/§4.1）；匹配交互的选项 `1-5/m/s/i/q`（PRD §5.7）。
- **可测性**：`Prompter` 必须能注入假输入序列，测试里走完整路径。
- **依赖**：T-17, T-18, T-19
- **单测**：`tests/test_menu_flow.py`：注入 `["1","1","1","y","0"]` 走通检查流程；注入 `"b"` 回退。

### T-22 `build/nuitka_build.py`（打包）

- **输出**：
  ```python
  def build(*, onefile: bool = False, output_dir: Path = Path("dist"), clean: bool = False) -> int: ...
  def main(argv: Sequence[str] | None = None) -> int: ...
  ```
- **命令模板**：
  ```
  <python> -m nuitka --standalone --assume-yes-for-downloads \
      --include-package=modcheck --include-package-data=modcheck \
      --nofollow-import-to=pytest --nofollow-import-to=_pytest \
      --nofollow-import-to=unittest --nofollow-import-to=pydoc --nofollow-import-to=doctest \
      --output-dir=dist --output-filename=modcheck \
      src/modcheck/__main__.py
  ```
  `--onefile` 时追加 `--onefile`。
- **验收**：`dist/modcheck/modcheck.exe --version` 能跑；产物目录里**没有** `pytest`/`_pytest`；把 `dist/modcheck` 整个目录复制到别处仍能运行。
- **依赖**：M0~M5 完成

### T-23 `tests/` 全套（见 §4）

### T-24 README 与示例环境

- **`README.md`**：中文；包含安装、四个典型命令、退出码表、常见问题、开发（跑测试、打包）、目录结构、CurseForge 未启用的说明。
- **`tests/make_fixtures.py`**（PM 验收要用）：用 `zipfile` 现场生成演示环境，**不提交任何二进制**：
  ```
  python tests/make_fixtures.py            # 生成 tests/_fixtures/mods_demo/ 与 tests/_fixtures/profiles/demo.json
  ```
  生成的 jar（内容最小可解析）：
  1. `[地毯] fabric-carpet-26.1+v260402.jar`（`fabric.mod.json` id=carpet，name="Carpet Mod"，version="26.1+v260402"）
  2. `lithium-fabric-0.12.1.jar`（id=lithium）
  3. `fabric-api-0.92.2+1.20.1.jar`（id=fabric-api）
  4. `server-extra.jar`（有 zip 结构但无模组元数据）
  5. `broken.jar`（100 字节随机内容）
  6. `old-mod.jar.disabled`（第 1 个文件的副本）
  生成的 `demo.json` 清单：carpet / lithium / fabric-api / jei / create / create-fabric / journeymap / 一个不存在的 slug（`no-such-mod-xyz`）。

---

## 4. 测试要求

### 4.1 总体

- `pytest -m "not live"` **必须全绿**，且**全程不联网**。
- `pytest -m live`：真实网络，默认跳过；只用于 T-12 的 5 条真实验证。
- **core 层覆盖率 ≥ 80%**（`pytest --cov=modcheck.core`，若未装 `pytest-cov` 则用 `trace` 手工统计，**不要**为此引入新依赖）。
- 假 Provider（`tests/conftest.py`）：
  ```python
  class FakeProvider(BaseProvider):
      """内存数据源：可注入 hits / projects / versions / 异常 / 延迟。"""
      def __init__(self, *, hits: Sequence[ProjectHit] = (), projects: dict[str, ProjectInfo] | None = None,
                   versions: dict[str, list[VersionInfo]] | None = None,
                   hash_map: dict[str, VersionInfo] | None = None,
                   raise_on: dict[str, Exception] | None = None, delay: float = 0.0) -> None: ...
  ```
- 假 HttpClient：注入假 `transport`（一个 `Callable[[Request], Response]`）与假 `sleep`/`clock`，**不产生真实等待**。
- `tests/fixtures/` 全部是文本 JSON，**不含二进制**；jar 由 `tests/make_fixtures.py` 现场用 `zipfile` 生成。

### 4.2 必含回归用例（**一条都不能少**）

| # | 用例 | 断言 |
|---|---|---|
| 1 | `parse_jar_filename("fabric-carpet-26.1+v260402.jar")` | name=`carpet`, mc=`26.1`, mod_version=`v260402`, cn_name=None |
| 2 | `parse_jar_filename("[地毯] fabric-carpet-26.1+v260402.jar")` | cn_name=`地毯` + 同上 |
| 3 | `parse_jar_filename("fabric-api-0.92.2+1.20.1.jar")` | mc=`1.20.1`；`"fabric-api" in name_candidates` |
| 4 | `parse_jar_filename("servercore-fabric-1.4.6+1.20.1.jar")` | mc=`1.20.1`（**不是** 1.4.6） |
| 5 | `parse_jar_filename("lithium-fabric-0.12.1.jar")` | mc is None；`"lithium" in name_candidates` |
| 6 | classify：carpet @ 26.1/fabric（A=26.3，B=26.1） | `DEGRADED / OLD_VERSION_ONLY` |
| 7 | classify：carpet @ 26.3/fabric（A=B=同一条） | `READY / OK` |
| 8 | classify：journeymap @ 26.3/fabric（4 条同版本号不同 loader、日期完全相同） | `READY / OK`（**防"全局最新"误判的核心回归**） |
| 9 | classify：jei @ 26.3/fabric（B 空、B2 非空） | `DEGRADED / PRERELEASE_ONLY` |
| 10 | classify：jei @ 26.1/fabric（B 非空、A[0]≠B[0]） | `DEGRADED / OLD_VERSION_ONLY` |
| 11 | classify：create @ 26.3/fabric（A 空、A2 空、version_count>0） | `BLOCKED / NO_LOADER` |
| 12 | classify：create-fabric @ 26.3/fabric | `BLOCKED / NO_MC_VERSION` 且 max_supported_mc 含 `1.20.1` |
| 13 | classify：A 空、A2 空、`version_count == 0` | `BLOCKED / **NO_FILES**`（**不得**报成 NO_LOADER） |
| 14 | 限流 / 超时 / 5xx | 该模组 `UNKNOWN / ERROR`，**绝不是 BLOCKED**；其余模组结论不受影响 |
| 15 | 用 `project_carpet.json`（`versions[]` 乱序，前 6 条是 2022 年） | 判定结果与"用正确端点"完全一致；源码里不得出现对该字段的排序或取首（**只允许取 `len()`**） |
| 16 | `read_jar_meta("broken.jar")` | 返回 `error != None`，不抛异常 |
| 17 | `sha1_of_file` 两次调用 | 结果相同且等于 `hashlib.sha1` 的期望值 |
| 18 | `normalize("ferrite-core") == normalize("ferritecore")` | True |
| 19 | `match_exact` 在 `search_chunky.json` 上 | 认定 `chunky`（slug 唯一命中），忽略 title 命中的 `newbiichunkymod` |
| 20 | `match_exact` 在 `search_carpet.json` 上（8 条） | 输入 `carpet` → 认定 `carpet`；输入 `Carpet TIS Addition` → `ambiguous=True`（不自动选） |
| 21 | `display_width("[地毯] Carpet")` | 13 |
| 22 | 渲染 golden（PRD §5.3 的 13 行样例） | 除时间戳与用时行外逐字节一致 |
| 23 | `scan` 对 `tests/_fixtures/mods_demo/` | 识别出 carpet/lithium/fabric-api；跳过 `broken.jar`/`server-extra.jar`/`old-mod.jar.disabled`；打印重复告警 |
| 24 | `load_profile` 对损坏 JSON | 抛 `ProfileError`，文案含 PRD E11 的关键句 |
| 25 | `--mc 26.4-snapshot-2` | 退出码 3 + PRD E08 文案 |
| 26 | `--mc abc` | 退出码 3 + PRD E07 文案 |
| 27 | 输出重定向 | 无 ANSI 转义（`"\x1b[" not in output`） |
| 28 | 缓存损坏 | `get` 返回 None、不抛、坏文件被删 |
| 29 | `--quiet` 渲染 | 🔴/🟡 组仍逐条列出；🟢 组只有一行计数；JSON 导出内容与不加 `--quiet` 时**完全一致** |
| 30 | 非交互模式未精确匹配 | 产出 ⚪ `UNMATCHED`，且 `on_unmatched` 回调**未被调用**（绝不猜） |

### 4.3 Fixture 清单（`tests/fixtures/`，全部为文本 JSON）

`search_carpet.json`（8 条真实命中）、`search_chunky.json`（含 `newbiichunkymod` 干扰项）、`project_carpet.json`（**保留乱序的 `versions[]` 字段**，用于用例 15）、`project_empty.json`（`versions[]` 为空，用于用例 13）、`versions_carpet_26.1_fabric.json`（1 条，文件名 `fabric-carpet-26.1+v260402.jar`）、`versions_carpet_26.3_fabric.json`、`versions_journeymap_26.3.json`（4 条同版本号不同 loader、时间完全相同）、`versions_jei_26.3_fabric.json`（release 空 + beta 有）、`versions_create.json`（无 fabric）、`versions_create_fabric.json`（最高 1.20.1）、`version_files_hit.json`、`version_files_empty.json`、`manifest_v2.json`（裁剪版，含 26.3/26.1 等）。

> 这些 fixture 可直接按基线 §17 的实测结论手工构造；**不要**把真实响应整体粘进来（体积太大）。

---

## 5. 明确不要做的事（防止过度设计）

1. ❌ 不要写 GUI / TUI 框架（`curses`、`textual` 都不要）。交互只要 `input()` + 编号菜单。
2. ❌ 不要引入任何第三方库（含 `rich` / `click` / `requests` / `colorama` / `wcwidth` / `tqdm`）。
3. ❌ 不要用 `asyncio`：`ThreadPoolExecutor` 足够。
4. ❌ 不要做依赖递归解析（只对 `fabric.mod.json.depends` 做一层提示，且不得影响三态判定）。
5. ❌ 不要用文件名解析结果做**任何**判定（基线 §11.2）。
6. ❌ 不要用 `/project/{id}` 的 `versions[]` 判断最新版（基线 §17.8）；**只允许取它的长度**。
7. ❌ 不要对 `/project/{id}/version` 的返回值重新排序（基线 §7：直接信任返回顺序）。
8. ❌ 不要全量拉取版本列表（基线 §9.5.1）。
9. ❌ 不要实现 CurseForge 的真实请求（占位 + 抛 `ProviderUnavailable`）。
10. ❌ 不要写死 API Key；不要读取用户的 `.minecraft` 目录；不要修改用户的 mods 文件夹。
11. ❌ 不要做"模糊匹配/相似度匹配"来自动认定项目（决策 A4 / PRD §1.4 的 C3 场景）。
12. ❌ 不要为测试引入网络 mock 框架（自己写 40 行的假 transport）。
13. ❌ 不要在 `core/` 里 `print`/`input`/`sys.exit`。
14. ❌ 不要把 `pytest` 写进 `dependencies` 或打包产物。
15. ❌ 不要为了"看起来更聪明"加自动修复、自动下载、自动禁用模组的功能。
16. ❌ 不要把 onefile 作为默认分发形态（主 Agent 实测首次启动约 7 秒）。

---

## 6. 常见陷阱（**踩过的坑，别再踩一次**）

| # | 陷阱 | 正确做法 |
|---|---|---|
| 1 | 拿 `date_published` 字符串排序 | 直接信任 API 顺序取首条；显示日期就原样显示 |
| 2 | 取 `/project/{id}.versions[0]` 当最新版 | 用 `/project/{id}/version?limit=1`（基线 §17.8） |
| 3 | `loaders` 参数手写成 `["fabric"]` | 用 `json.dumps` + `urlencode` |
| 4 | 404 时直接 `json.loads(resp)` | 先判空体（Modrinth 的 404 体是空的） |
| 5 | 文件名解析出的 MC 版本进判定 | 只作 `detected.mc_versions` 提示 |
| 6 | 把 `0.92.2` 当 MC 版本 | 用官方清单锚点，或 `major ≥ 20` / `major==1 and minor≥7` |
| 7 | 用全局最新版判定 | 一律 `latest_for_loader`（JourneyMap 案例） |
| 8 | 网络错误标红 | 一律 ⚪ `UNKNOWN/ERROR` |
| 9 | 单模组异常冒泡终止整个检查 | `check_mods` 里逐模组 `try/except` |
| 10 | 大 jar 整包读进内存 | 只读需要的成员 + 单成员 2 MB 上限 + sha1 流式 |
| 11 | Windows 中文乱码 | 启动时 `reconfigure(encoding="utf-8")` + `SetConsoleOutputCP(65001)` |
| 12 | 用 `len(s)` 算列宽 | 用 `display_width`（CJK 算 2） |
| 13 | 表格里用 emoji | 表格内只用 `✓ ! ✗ ? ·`（PRD §5.3） |
| 14 | 进度条残留在报告里 | 渲染报告前 `clear_progress()` |
| 15 | 缓存写一半断电 | 先写 `.tmp` 再 `os.replace` |
| 16 | 对 200 个模组开 20 个线程 | 默认 6，硬上限 8，并加全局令牌桶 |
| 17 | Nuitka 打包时交互式卡住 | 必须加 `--assume-yes-for-downloads`（见 ENGINEERING_CONTRACT §1.2） |
| 18 | pip / Nuitka 写到用户目录被沙箱拒绝 | `PIP_CACHE_DIR` / `NUITKA_CACHE_DIR` / `TEMP` 指向工作区内（见 ENGINEERING_CONTRACT §1.1） |

---

## 7. 交付物定义（DoD）

与 `docs/ENGINEERING_CONTRACT.md` §5 的 DoD **合并执行**，本项目的额外要求：

1. `src/modcheck/` 完整实现，`modcheck.cmd` / `modcheck.sh` 可用。
2. `pytest tests -m "not live"` **全绿**（用 `.toolchain\Python311\python.exe -m pytest`）；core 覆盖率 ≥ 80%。
3. `dist/modcheck/modcheck.exe`（standalone）真实打包成功，能运行 `--version` 与一次 `check`；产物中文不乱码。
4. `README.md` 中文，含四个典型命令、退出码表、**onefile 首次启动约 7 秒的说明**。
5. `tests/make_fixtures.py` 可生成 PM 验收所需的演示环境。
6. 全部用户可见文案来自 `i18n.py`，且与 PRD §5 逐字一致。
7. 无第三方运行时依赖（`pyproject.toml` 的 `dependencies` 为空）。
8. `docs/PM_REVIEW_CHECKLIST.md` 里 **A~H 组**能跑通（I/J 组依赖性能与打包，尽力而为）。

---

## 8. 遇到不确定时怎么办

1. **文案**：以 `docs/PRD.md` §5 为唯一标准；PRD 没写的，用同风格补，并**在交付说明里列出**。
2. **判定逻辑**：以基线 §7 + PRD §4.3 为准；两者冲突时**以基线为准**并回报。
3. **API 行为**：以基线 §17 的实测证据为准；不确定就写离线 fixture + 一条 `live` 测试，不要凭猜。
4. **编码/打包规范**：以 `docs/ENGINEERING_CONTRACT.md` 为准。
5. **任何"要不要顺手加个功能"的念头**：先查 PRD §8「范围边界」与本文 §5「不要做的事」，大概率答案是不加。
6. **需求本身有歧义**：不要猜，写进交付总结等主 Agent 确认。
