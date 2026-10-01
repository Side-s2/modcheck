# 附录 18：Nuitka 打包后的运行时标记实测（2026-10-01）

> 环境：Nuitka 4.2.2 ｜ Python 3.11.9 ｜ Windows ｜ MinGW-w64 gcc 15.2.0（Nuitka 自带 winlibs）
> 方法：真机编译探针程序并在 `--standalone` 与 `--onefile` 两种模式下运行，打印运行时标记。
> 脚本：`.toolchain/probe_main.py` + `.toolchain/probe_pkg/inner.py`（临时探针，结论已固化到本文）

## 实测结果

| 检测方式 | 源码运行 | Nuitka standalone | Nuitka onefile |
|---|---|---|---|
| `getattr(sys, "frozen", False)` | missing | **missing** | **missing** |
| `"__compiled__" in globals()`（主模块） | False | **True** | **True** |
| `"__compiled__" in globals()`（**子模块**） | False | **True** | **True** |
| `hasattr(sys, "__compiled__")` | False | False | False |
| `sys.argv[0]` | 脚本路径 | **exe 真实路径** | **exe 真实路径** |
| `sys.executable` | python.exe | `<dist>\python.exe` | **`%TEMP%\onefile_xxx\python.exe`** |

## 三条结论（必须遵守）

1. **`sys.frozen` 对 Nuitka 无效** —— 两种打包模式下都不存在。任何 `if getattr(sys, "frozen", False)` 的检测在 Nuitka 产物里**恒为假**。
2. **唯一可靠的打包标记是模块级 `__compiled__`** —— 它在**每一个**被编译的模块里都存在（含子模块），所以包内任意模块都可以用 `"__compiled__" in globals()` 判断。
3. **定位 exe 目录必须用 `sys.argv[0]`，不能用 `sys.executable`** ——
   - standalone：`sys.executable = <dist>/python.exe`，恰好与 exe 同目录，能"碰巧正确"；
   - **onefile：`sys.executable = %TEMP%/onefile_xxx/python.exe`，是解包用的临时目录，进程退出即删除**；
   - `sys.argv[0]` 在两种模式下都是真正的 exe 路径。

## 对产品的影响

- 便携模式（用户明确要求"配置存在程序文件夹内"）依赖 exe 目录探测。用 `sys.frozen` 会**静默失效**，配置跑到 `%APPDATA%` 且没有任何提示。
- 若改用 `sys.executable`，**onefile 会把用户配置写进会被删除的临时目录** —— 用户建立的模组清单会在下次启动时消失。

## 推荐的实现

```python
def is_packaged() -> bool:
    return "__compiled__" in globals() or bool(getattr(sys, "frozen", False))

def detect_exe_dir() -> Path | None:
    if not is_packaged():
        return None
    raw = (sys.argv[0] if sys.argv and sys.argv[0] else "") or sys.executable
    try:
        return Path(raw).resolve().parent
    except OSError:
        return Path(sys.executable).resolve().parent
```
