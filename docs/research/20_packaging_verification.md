# 附录 20：Nuitka 打包端到端验证（2026-10-01）

> 环境：Nuitka 4.2.2 ｜ Python 3.11.9 ｜ Windows ｜ gcc 15.2.0（Nuitka 自动下载的 winlibs）
> 构建入口：build/nuitka_build.py ｜ 验证人：主 Agent（真机编译 + 真机运行）

## 结果总表

| 项 | standalone | onefile |
|---|---|---|
| 构建 | 成功 | 成功（第二次；见『偶发失败』） |
| 产物 | modcheck.exe（9.5 MB） | __main__.exe（7 MB，**命名待修**） |
| --version | modcheck 0.1.0 | modcheck 0.1.0 |
| 首次启动 | < 1 s | **7.6 s**（解包） |
| **config path** | 在 exe 同级目录 | **在 exe 同级目录** |
| config/ 是否真的创建 | 是 | 是 |
| 端到端扫真实 30 模组 | 30/30 | 30/30 |

## 最关键的结论：便携配置目录在两种模式下都生效

这正是 D29 要防的两个坑：
1. sys.frozen 在 Nuitka 下**不存在** —— 若用它检测，便携模式会静默失效、配置跑到 %APPDATA%；
2. onefile 的 sys.executable 指向 %TEMP%/onefile_xxx/python.exe —— 若用它定位，**用户清单会写进退出即删的临时目录**。

实测确认：两种模式输出的 config path 都在 exe 同级，说明 `__compiled__` + `sys.argv[0]` 的修法是正确的。

## 偶发失败记录（供排查参考）

第一次 onefile 构建（与 standalone 在同一 PowerShell 会话里连续执行）失败：

    exit=1
    nuitka/build/include/nuitka/constants.h:246:10:
      fatal error: __constants.h: No such file or directory

单独重跑即成功。判断为 C 后端中间产物（__constants.h 属于构建目录生成物）的**瞬时/残留状态问题**，不是代码问题。
建议在 build/nuitka_build.py 里默认加 --remove-output，减少残留干扰。

## 待修（不影响功能）

1. **onefile 产物命名是 __main__.exe**：--output-filename=modcheck 只在 standalone 分支被追加，onefile 分支漏了；_fix_dist_name() 也没处理 onefile 的 exe 本体。应统一为 modcheck.exe。
2. **构建目录残留**：输出目录里留下 __main__.build / __main__.onefile-build，建议默认 --remove-output 或构建后清理。
3. pkg-standalone 里出现过 0 MB 的 __main__.dist/modcheck.exe —— 失败那次留下的空壳，构建脚本可考虑先清理输出目录。