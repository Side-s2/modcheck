# 附录 30：跨平台兼容性审计（2026-10-01）

## 结论先说：**Windows 已运行时验证；Linux 只做了静态审计**

本机没有可用的 Linux 运行时 —— Docker CLI 存在但守护进程未启动，WSL 存在但无发行版（Wsl/E_ACCESSDENIED）。
因此 **Linux 兼容性无法在本机做运行时验证**，这是必须写进交付说明的已知局限，不能含糊过去。

## 静态审计结果（脚本：docs/research/28_platform_compat_audit.py）

| 检查项 | 结果 |
|---|---|
| Windows 专属 API（ctypes.windll）是否在平台分支内 | ✅ 2 处全部有 sys.platform 保护（console.py:58/69） |
| 裸导入 POSIX 模块（termios/fcntl/pwd/grp/resource） | ✅ 无 |
| shutil.get_terminal_size | ✅ 传了 fallback，跨平台安全 |
| 硬编码 Windows 路径 / 字符串拼路径 | ✅ 无真问题（唯一命中是 User-Agent URL，误报） |
| 文件读写显式 encoding | ✅ 全部显式（两处疑似分别是二进制读与 URL 打开，误报） |

## 第二个脚本（docs/research/29_linux_gap_check.py）

- 测试套件里没有 Windows-only 假设；
- 源码用 pathlib 而非字符串拼路径。

## 一处小瑕疵（无害）

modcheck.sh:6 检测 .toolchain/Python311/python.exe —— 但 Linux 上那个文件不存在（也没有 .exe 后缀），
所以这一分支在 Linux 上是死代码，会直接落到 PY=python3。功能上没问题（用系统 python3），
但若打算在 Linux 上放自带工具链，路径写法需要调整。

## 交付时必须写明

> **Linux 未经运行时验证。** 代码层面已做跨平台静态审计（无 Windows 专属依赖、无 POSIX 裸导入、
> 路径全用 pathlib、编码全显式），但**没有在真实 Linux 上跑过**。首次在 Linux 部署时请先跑
> python3 -m pytest（离线用例）确认环境无误。