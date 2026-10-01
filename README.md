# modcheck —— Minecraft 模组版本检查工具

在**升级服务端游戏版本之前**，一条命令查清你服务器上的模组是否都已经支持目标版本与加载器，
并把结论分成「就绪 / 需降级 / 阻塞 / 未判定」四类，每条都给出下一步该做什么。

- 全中文界面，Windows 与 Linux 表现一致
- 零第三方运行时依赖（只用 Python 3.11 标准库）
- **绝不猜**：查不到就报「未判定」，不会为了看起来完整而随便选一个
- 只读你的 mods 文件夹，**不下载、不修改、不安裝任何模组**

---

## 1. 快速开始

Windows（仓库根目录已带启动脚本，会自动使用 `.toolchain\Python311`）：

```bat
modcheck.cmd --help
modcheck.cmd                       :: 无参数 -> 交互式菜单
```

Linux / macOS：

```sh
./modcheck.sh --help
```

也可以直接用解释器运行：

```bat
set PYTHONPATH=src
.toolchain\Python311\python.exe -m modcheck --help
```

## 2. 四个典型命令

```bat
:: ① 扫描 mods 文件夹建立模组清单（读 jar 内元数据 + 文件指纹反查 Modrinth）
modcheck.cmd scan "C:\servers\survival\mods" --profile 服务器A

:: ② 检查整份清单在目标版本 + 加载器下能不能用
modcheck.cmd check --profile 服务器A --mc 26.3 --loader fabric

:: ③ 只看官方正式版列表（不知道填什么版本号时用）
modcheck.cmd versions --limit 10

:: ④ 把报告导出留档 / 贴群里（文件名自动带版本与时间）
modcheck.cmd check --profile 服务器A --mc 26.3 --loader fabric --json report.json --md report.md
```

没有 jar、只有一份文件名清单时（例如朋友发来的截图，你敲成了 txt）：

```bat
modcheck.cmd scan --from-list 文件名清单.txt --profile 服务器A
```

> ⚠️ 这种模式下**所有条目都是靠文件名猜的**（报告里 modid 前带 `~`），
> 结论仅供参考，请人工核对。补上 jar 文件后重新扫描可以变成确定结果。

## 3. 退出码

| 码 | 含义 | 典型场景 |
|---|---|---|
| 0 | 全部就绪 / 仅需降级 | 可以直接升级（需降级项自己拍板） |
| 1 | 存在阻塞项 | 有模组在目标版本下没有任何可用版本 |
| 2 | 存在未判定项且无阻塞 | 网络问题、没能精确同名匹配 |
| 3 | 参数 / 配置错误 | 版本号写错、清单损坏、导出失败 |
| 4 | 数据源整体不可用 | 一个可用数据源都没有 |
| 130 | 用户中断（Ctrl+C） | 检查被中断，已输出已完成部分 |

## 4. 常见问题

**中文显示成乱码？**
程序启动时会自动把终端切到 UTF-8（Windows 上还会设置控制台代码页 65001）。
若仍异常，可先执行 `chcp 65001`，或设置环境变量 `PYTHONIOENCODING=utf-8`。

**国内网络连不上？**

```bat
modcheck.cmd config set proxy http://127.0.0.1:7890
```

**为什么 CurseForge 显示「未启用（缺少 API Key）」？**
CurseForge 的 v1 API 必须有 API Key，本期没有实现（见 `src/modcheck/providers/curseforge.py` 里的补全说明）。
没有启用它**不会**报错，也不会把模组算成红色——只会让只发布在 CurseForge 上的模组落到「未判定」。

**第二次检查为什么快很多？**
结果会缓存到配置目录（Modrinth 默认 6 小时）。用 `--refresh` 可以强制重新请求；
`modcheck.cmd cache info` / `cache clear` 可以查看与清理。

**打包版为什么有 standalone 和 onefile 两种？**
standalone 目录启动 < 1 秒，是默认交付形态；`--onefile` 只有一个 6.2 MB 的 exe，
但**首次启动需要约 7 秒**（要先解包到临时目录），之后才会快。

## 5. 开发

```bat
:: 跑测试（默认离线，不联网）
.toolchain\Python311\python.exe -m pytest

:: 真实网络测试（默认跳过）
.toolchain\Python311\python.exe -m pytest -m live

:: 生成演示用的 jar 与清单（不提交任何二进制）
.toolchain\Python311\python.exe tests\make_fixtures.py

:: 打包（standalone；加 --onefile 生成单文件）
.toolchain\Python311\python.exe build\nuitka_build.py
```

## 6. 目录结构

```
src/modcheck/
  core/         纯逻辑：models / mcversion / filename / jarmeta / matching / checker / report
  providers/    网络数据源：http（限速退避缓存） / modrinth / mojang / curseforge（占位） / registry
  storage/      本地存储：paths（配置目录） / settings / profiles
  cli/          命令行：main / menu / prompts / render / context / commands/*
docs/           项目文档（基线、PRD、工程契约、程序员任务书）
tests/          pytest（离线夹具 + live 用例）
build/          Nuitka 打包脚本
```

分层依赖方向严格单向：`cli -> core <- providers`、`cli -> storage`。
`core` 与 `storage` 里没有 `print` / `input` / `sys.exit`，所以未来可以直接被 GUI 复用。
