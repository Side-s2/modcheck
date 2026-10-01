# 工程师契约（Programmer Contract）

> 本文档由主 Agent 维护，是程序员子代理的**常驻规范**。每一轮迭代都必须遵守。
> 与 `docs/PROJECT_BRIEF.md` 配合阅读：BRIEF 讲"做什么"，本文档讲"怎么做得对"。

---

## 0. 角色定义

你是本项目的 **Software Engineer**。你按 `docs/TASKS_FOR_PROGRAMMER.md` 施工，交付**可运行、可测试、可打包**的代码。
你不改需求（有疑问就记下来问主 Agent），不擅自扩大范围。

---

## 1. 开发环境（**已就绪，直接用，不要另装**）

| 项 | 值 |
|---|---|
| 目标解释器 | `D:\Programme\python_prgram\mod-version-checker\.toolchain\Python311\python.exe`（**Python 3.11.9**） |
| pytest | 9.1.1（已装） |
| Nuitka | 4.2.2（已装） |
| 工作目录 | `D:\Programme\python_prgram\mod-version-checker` |

> ⚠️ **系统里的 `python` 是 3.13，不是目标版本。** 跑测试/打包一律用上面那个 3.11 的绝对路径，或先把它加进 PATH：

```powershell
$py = "D:\Programme\python_prgram\mod-version-checker\.toolchain\Python311\python.exe"
& $py -m pytest                       # 跑测试
& $py -m modcheck --help              # 跑 CLI（需先设置 PYTHONPATH=src，或用 pip install -e .）
```

### 1.1 沙箱约束（**踩过的坑，必须照做**）

本机文件沙箱**只允许写工作区**。以下环境变量**必须**指向工作区内，否则 pip / Nuitka 会因为"拒绝访问"而失败或卡死：

```powershell
$root = "D:\Programme\python_prgram\mod-version-checker"
$env:PIP_CACHE_DIR    = "$root\.toolchain\pip-cache"
$env:NUITKA_CACHE_DIR = "$root\.toolchain\nuitka-cache"
$env:TEMP = "$root\.toolchain\tmp"; $env:TMP = $env:TEMP
$env:PYTHONIOENCODING = "utf-8"
```

### 1.2 Nuitka 打包的额外约束（**已实测**）

- ❌ 系统自带的 MinGW gcc 8.1.0 会被 Nuitka **拒绝**（"Only this specific gcc is supported"）
- ✅ 必须加 `--assume-yes-for-downloads`，让 Nuitka 自动下载它配套的 winlibs-gcc 到 `NUITKA_CACHE_DIR`
- ✅ **主 Agent 已在本机真机验证**：standalone 与 onefile 两种模式都能成功构建并运行，产物中文输出正常
  - standalone：启动快（< 1 s），推荐默认
  - onefile：6.2 MB 单文件，但**首次启动需 7.09 秒**解包 → 只作为可选产物，必须写进文档告知用户
  - 构建时会自动下载 winlibs-gcc 15.2.0 与 depends.exe 到 `NUITKA_CACHE_DIR`，首次构建约 3~5 分钟，之后走缓存
  - 出现 `Cannot find Windows Runtime DLLs to include` 是**无害警告**（控制台程序不依赖 WinRT），不必处理
- 构建命令模板：

```powershell
& $py -m nuitka --assume-yes-for-downloads --standalone --output-dir=dist `
    --include-package=modcheck --noinclude-pytest-mode=nofollow `
    --nofollow-import-to=pytest --nofollow-import-to=_pytest `
    --nofollow-import-to=unittest --nofollow-import-to=pydoc `
    src\modcheck\__main__.py
```

---

## 2. 硬性规则（违反即返工）

| # | 规则 | 说明 |
|---|---|---|
| 1 | **零第三方运行时依赖** | 只用标准库。pytest 只是开发依赖，**绝不能**被 import 到 `src/modcheck/` 里 |
| 2 | **Python 3.11 语法基线** | 禁用 3.12+ 独有语法（`type` 别名语句、PEP 701 f-string 嵌套引号等）。`match`、`X \| Y`、`tomllib` 可用 |
| 3 | **core / storage 层绝对纯净** | 禁止 `print`、`input`、`sys.exit`、写 stdout/stderr。所有展示交 `cli/`。GUI 复用全靠这条 |
| 4 | **所有用户可见文案集中在 `modcheck/i18n.py`** | 代码里不许出现中文字符串字面量（i18n.py 本身除外） |
| 5 | **编码显式** | 所有 `open()` 必须写 `encoding="utf-8"`；JSON 用 `ensure_ascii=False` |
| 6 | **不裸抛异常** | 网络/解析/IO 错误一律转成 `modcheck.errors` 里的领域异常；单个模组失败**不得**中断整体检查 |
| 7 | **原子写盘** | 配置文件与缓存必须"先写 `.tmp` 再 `os.replace()`" |
| 8 | **路径一律 `pathlib.Path`** | 禁止字符串拼路径；禁止硬编码 `/\\` 分隔符 |
| 9 | **跨平台** | 平台相关代码必须 `sys.platform` 分支；Windows 专属逻辑不得影响 Linux 运行 |
| 10 | **不猜** | 匹配不到就报 ⚪ 未判定，**绝不**为了"看起来完整"而随便选一个候选（见 BRIEF 第 8 节） |

---

## 3. 编码规范

1. **类型注解**：所有公开函数/方法必须有完整类型注解（参数 + 返回值）。用 `from __future__ import annotations` 保持前向引用简洁。
2. **数据模型**：值对象用 `@dataclass(frozen=True)`；枚举用 `enum.Enum`（`str, Enum` 混入便于序列化）。
3. **文档字符串**：模块、类、公开函数写**中文** docstring，说明职责、参数、返回、可能抛出的领域异常。
4. **行长** ≤ 110 字符。
5. **禁止 `from x import *`**。
6. **副作用隔离**：`core/` 里不得有模块级副作用（不建目录、不发请求、不读配置）。
7. **依赖注入**：`core` 通过参数接收 Provider 与 `Clock`/`Cache` 接口，**不得** import 具体实现。这样测试才能注入假对象。
8. **命名**：模块/函数/变量 `snake_case`，类 `PascalCase`，常量 `UPPER_SNAKE`；领域术语保持与 BRIEF 一致（`Status.READY / DEGRADED / BLOCKED / UNKNOWN`，`reason_code` 取值必须与 BRIEF 第 7 节表格逐字一致）。
9. **注释写"为什么"**，不写"是什么"。踩过的坑要留注释（例如 `# /project 的 versions[] 不是倒序的，别用它判断最新版`）。

---

## 4. 测试规范

1. **框架**：pytest。测试文件放 `tests/`，命名 `test_<模块>.py`。
2. **默认离线**：真实网络测试必须标 `@pytest.mark.live`，且 `pyproject.toml` 里已配置默认 deselect。
3. **假 Provider**：在 `tests/fakes.py` 里实现 `FakeProvider`，用内存数据模拟 Modrinth。**core 的测试一律用它**。
4. **HTTP 层**：用一个可注入的 `transport` 函数替身来模拟，不要在测试里 monkeypatch `urllib` 全局。
5. **必须有的回归用例**（这些是主 Agent 实测确认过的真实行为）：
   - 文件名解析：`[地毯] fabric-carpet-26.1+v260402.jar` → name=`carpet`, mc=`26.1`, modver=`v260402`, cn=`地毯`
   - 文件名解析失败案例：`lithium-fabric-0.12.1.jar` **不得**解析出 MC 版本；`servercore-fabric-1.4.6+1.20.1.jar` **不得**把 `1.4.6` 当 MC 版本（必须断言不确定）
   - 三态判定（用假 Provider 构造）：
     - 目标加载器最新版支持目标 MC → 🟢 `OK`
     - 有兼容旧版但最新版不支持 → 🟡 `OLD_VERSION_ONLY`
     - 只有 beta 支持 → 🟡 `PRERELEASE_ONLY`
     - 没有任何该加载器的文件 → 🔴 `NO_LOADER`
     - 有该加载器文件但都不支持目标 MC → 🔴 `NO_MC_VERSION`
     - **多加载器同版本号陷阱**：构造 paper/forge/fabric 三条同日期的版本，断言 fabric 目标下必须是 🟢（这条是重点回归项）
     - 网络异常 → ⚪ `ERROR`（**绝不能是红色**）
   - 匹配规则：`normalize("ferritecore") == normalize("ferrite-core")` → 完全同名认定
   - 匹配规则：slug 唯一命中优先于多个 title 命中
   - 无精确同名 → 非交互模式下必须产出 ⚪ `UNMATCHED`，不得自动选一个
   - 配置文件损坏 → 抛领域异常并给出中文提示，不得 traceback
   - 清单合并去重：同 modid 多次扫描只留一条
6. **覆盖率**：`src/modcheck/core/` ≥ 80%（用 `pytest --cov` 或人工核对，不要为此引入运行时不依赖的包以外的负担）。

---

## 5. 完成定义（Definition of Done）

一轮迭代只有在**全部满足**时才算完成：

- [ ] `& $py -m pytest` **全绿**（0 failed / 0 error）
- [ ] 手工冒烟：`modcheck`（无参数）能进菜单；`modcheck check --help` 正常；用假清单能跑出分组报告
- [ ] 没有 `TODO` 占位（`providers/curseforge.py` 的预留占位除外，那是**故意**的）
- [ ] `src/modcheck/` 里没有中文字符串字面量（i18n.py 除外）
- [ ] `src/modcheck/core/` 与 `storage/` 里没有 `print`/`input`
- [ ] 所有 `open()` 都带 `encoding="utf-8"`
- [ ] 在**无颜色**模式下（`--no-color`）与**管道**下（`| more`）输出都不乱码、不错行
- [ ] 报告一份**自测总结**给主 Agent：跑了什么、结果如何、哪些没做到及原因

---

## 5.1 已验证的构建脚本骨架（可直接采用）

```python
# build/nuitka_build.py —— 已验证可用的构建入口
import argparse, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def main() -> int:
    ap = argparse.ArgumentParser(description="使用 Nuitka 打包 modcheck")
    ap.add_argument("--onefile", action="store_true", help="生成单文件（首次启动较慢）")
    ap.add_argument("--output-dir", default="dist")
    args = ap.parse_args()

    env = dict(os.environ)
    env.setdefault("NUITKA_CACHE_DIR", str(ROOT / ".toolchain" / "nuitka-cache"))
    cmd = [sys.executable, "-m", "nuitka",
           "--assume-yes-for-downloads",          # 必须：否则 Nuitka 交互式询问并中止
           "--onefile" if args.onefile else "--standalone",
           f"--output-dir={args.output_dir}",
           "--include-package=modcheck",
           "--nofollow-import-to=pytest",
           "--nofollow-import-to=_pytest",
           "--nofollow-import-to=unittest",
           "--nofollow-import-to=pydoc",
           "--company-name=modcheck",
           "--product-name=modcheck",
           str(ROOT / "src" / "modcheck" / "__main__.py")]
    return subprocess.call(cmd, cwd=str(ROOT), env=env)

if __name__ == "__main__":
    raise SystemExit(main())
```

---

## 6. 与主 Agent 的协作规则

- 遇到**需求不明确**：不要猜，在交付总结里列出来，等主 Agent 确认。
- 遇到**技术阻塞**（沙箱、网络、工具链）：不要反复重试同一个动作，报告出来。
- **不要修改** `docs/PROJECT_BRIEF.md`；那是主 Agent 的资产。你自己的设计说明写在 `docs/IMPLEMENTATION_NOTES.md`。
- 每轮迭代结束，代码要处于**可运行状态**，不要留半成品。
