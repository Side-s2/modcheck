"""终端输出：编码、颜色、VT、宽度对齐与进度行。

本模块是少数允许直接写 stdout 的地方之一（另一个是 cli/）。
它负责三件容易踩坑的事：
  ① Windows 控制台的代码页与流编码（中文乱码的根因，见基线 §17.5）；
  ② 颜色能力探测（管道/重定向/NO_COLOR 一律关闭）；
  ③ CJK 全角字符的显示宽度对齐（用 len() 算列宽一定会错位）。
"""
from __future__ import annotations

import ctypes
import os
import shutil
import sys
import unicodedata
from typing import TYPE_CHECKING, Final, TextIO

from modcheck.i18n import t

if TYPE_CHECKING:  # 只为类型注解，运行时不引入 core
    from modcheck.core.models import Status

# 单宽符号，表格内禁止 emoji（PRD §5.3：各终端 emoji 宽度算法不一致会错位）
SYMBOL_READY: Final[str] = "✓"
SYMBOL_DEGRADED: Final[str] = "!"
SYMBOL_PRERELEASE: Final[str] = "~"
SYMBOL_BLOCKED: Final[str] = "✗"
SYMBOL_UNKNOWN: Final[str] = "?"
SYMBOL_IGNORED: Final[str] = "·"

_COLOR_RESET: Final[str] = "\x1b[0m"
_COLOR_BY_STATUS: Final[dict[str, str]] = {
    "ready": "32",                 # 绿
    "degraded": "33",              # 黄
    # 橙。用 256 色的 208：Win10+ 的 conhost 与 Windows Terminal 都支持 VT + 256 色；
    # 万一终端不支持 256 色，也只是退化成近似色，不会乱码，所以是安全选择。
    "prerelease": "38;5;208",
    "blocked": "31",               # 红
    "unknown": "90",               # 灰
    "ignored": "90",
}


def init_terminal_encoding() -> str:
    """把终端与标准流切到 UTF-8；任何异常都吞掉，绝不崩溃。

    返回：
        "utf-8" 表示已尽力切换成功；"legacy" 表示部分步骤失败（中文可能异常）。
    """
    ok = True
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            ok = False
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            ok = False
    if sys.platform == "win32":
        try:
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)  # type: ignore[attr-defined]
        except Exception:
            ok = False
    return "utf-8" if ok else "legacy"


def enable_windows_vt() -> bool:
    """在 Windows 控制台上打开 ANSI 转义支持；非 Windows 恒为 True。"""
    if sys.platform != "win32":
        return True
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        enable_vt = 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        return bool(kernel32.SetConsoleMode(handle, mode.value | enable_vt))
    except Exception:
        return False


def console_attached() -> bool:
    """进程是否挂着一个真实的控制台窗口。

    Windows 上用 GetConsoleWindow()；其它平台退化为"stdin/stdout 至少一个是 tty"。
    """
    if sys.platform == "win32":
        try:
            return bool(ctypes.windll.kernel32.GetConsoleWindow())  # type: ignore[attr-defined]
        except Exception:
            return False
    try:
        return bool(sys.stdin is not None and sys.stdin.isatty())
    except Exception:
        return False


def ensure_console_streams() -> bool:
    """Windows：把**丢失的**标准流重新接回控制台（双击启动时的自救）。

    实测背景：用户双击单文件 exe 时「窗口一闪而过」。根因是 Nuitka onefile 的子进程
    没有可用的 stdin —— sys.stdin.isatty() 为假，菜单判定「非交互」直接退出 3，
    控制台窗口随之关闭，用户什么都看不到。而进程**其实还挂着控制台**
    （GetConsoleWindow() != 0），所以可以直接打开 CONIN$ / CONOUT$ 顶上。

    ⚠️ 只接管**已经失效**的句柄（GetFileType == FILE_TYPE_UNKNOWN）：
      * 用户重定向到文件 -> FILE_TYPE_DISK，绝不能抢；
      * 管道（echo 0 | modcheck）-> FILE_TYPE_PIPE，也绝不能抢。
    返回：是否做了替换。
    """
    # ⚠️ 只在**打包产物**上自救。源码/启动器（modcheck.cmd）一定是人在终端或脚本里跑的：
    # 那里把"非交互退出"改成"进菜单等输入"会让自动化调用挂死（实测踩过）。
    # 打包产物是给用户双击的，所以它要尽力把控制台找回来。
    from modcheck.storage.paths import is_packaged

    if sys.platform != "win32" or not is_packaged() or not console_attached():
        return False
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    except Exception:
        return False
    changed = False
    for std_handle, mode, device in ((-10, "r", "CONIN$"), (-11, "w", "CONOUT$")):
        try:
            handle = kernel32.GetStdHandle(std_handle)
            if kernel32.GetFileType(handle) != 0:   # 0 = FILE_TYPE_UNKNOWN -> 句柄已失效
                continue
            stream = open(device, mode, encoding="utf-8", errors="replace", buffering=1)
        except Exception:
            continue
        if std_handle == -10:
            sys.stdin = stream
        else:
            sys.stdout = stream
        changed = True
    return changed


def pause_before_exit(prompt: str = "") -> None:
    """让控制台窗口停住，好让用户看清最后几行。

    只在**挂着控制台**时调用（双击场景）。直接从 CONIN$ 读，绕开"stdin 是 NUL"这类
    退化情况 —— 那种情况下读 sys.stdin 会立刻 EOF，窗口照样会关掉。
    """
    if not console_attached():
        return
    try:
        sys.stdout.write(prompt)
        sys.stdout.flush()
    except Exception:
        pass
    try:
        if sys.platform == "win32":
            with open("CONIN$", "r", encoding="utf-8", errors="replace") as handle:
                handle.readline()
        elif sys.stdin is not None:
            sys.stdin.readline()
    except Exception:
        pass


def resolve_width(fallback: int = 100) -> int:
    """取输出宽度；非 TTY 时优先 COLUMNS，其次用 100（不用 shutil 默认的 80）。"""
    env = os.environ.get("COLUMNS")
    if env:
        try:
            value = int(env)
            if value > 0:
                return value
        except ValueError:
            pass
    try:
        if sys.stdout is not None and sys.stdout.isatty():
            return shutil.get_terminal_size(fallback=(fallback, 24)).columns
    except Exception:
        pass
    return fallback


def display_width(text: str) -> int:
    """按终端显示宽度计算字符串长度（全角/宽字符算 2 列）。"""
    width = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        width += 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
    return width


def truncate(text: str, width: int) -> str:
    """按显示宽度截断，超长时末尾加省略号。"""
    if width <= 0:
        return ""
    if display_width(text) <= width:
        return text
    out: list[str] = []
    used = 0
    for ch in text:
        step = 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
        if used + step > width - 1:
            break
        out.append(ch)
        used += step
    return "".join(out) + "…"


def pad(text: str, width: int) -> str:
    """按显示宽度右侧补空格（左对齐）。"""
    space = width - display_width(text)
    return text + " " * space if space > 0 else text


class Console:
    """统一输出门面；颜色与宽度都在这里决定，调用方只给纯文本。"""

    def __init__(self, *, stream: TextIO | None = None, color: str = "auto",
                 width: int | None = None, quiet: bool = False) -> None:
        self.stream: TextIO = stream if stream is not None else sys.stdout
        self.quiet = quiet
        self.width = width if width is not None else resolve_width()
        self.color_enabled = self._resolve_color(color)
        self._progress_len = 0
        try:
            self.is_tty = bool(self.stream.isatty())
        except Exception:
            self.is_tty = False
        if not self.is_tty:
            # 非 TTY 不做宽度裁剪：重定向到文件时"信息完整"优先于"排版好看"
            self.width = max(self.width, 200)

    def _resolve_color(self, color: str) -> bool:
        if color == "never":
            return False
        if os.environ.get("NO_COLOR"):
            return False
        try:
            if not self.stream.isatty():
                return False
        except Exception:
            return False
        if sys.platform == "win32" and not enable_windows_vt():
            return False
        return True

    # ---------------------------------------------------------------- 基础输出
    def line(self, text: str = "") -> None:
        """输出一行（自动先清掉进度行）。"""
        self.clear_progress()
        self._write(text + "\n")

    def raw(self, text: str) -> None:
        """输出不带换行的原始文本。"""
        self._write(text)

    def wrap(self, text: str, width: int | None = None) -> list[str]:
        """按显示宽度把一行文字折成多行（CJK 安全，保留原缩进）。

        窄终端里"原因/建议"这类说明文字**折行**比截断更有用：
        截断会把关键结论吃掉，折行至少信息还在。
        """
        limit = max(8, (self.width if width is None else width))
        if display_width(text) <= limit:
            return [text]
        indent = text[:len(text) - len(text.lstrip(" "))]
        out: list[str] = []
        current = ""
        used = 0
        for ch in text.strip():
            step = 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
            if used + step > limit - display_width(indent):
                out.append(indent + current)
                current, used = "", 0
            current += ch
            used += step
        if current:
            out.append(indent + current)
        return out

    def prose(self, text: str) -> None:
        """输出一段说明文字（必要时折行）。"""
        for chunk in self.wrap(text):
            self.line(chunk)

    def rule(self, ch: str = "─") -> None:
        """输出一条铺满终端宽度的分隔线。"""
        self.line(ch * max(1, self.width))

    def group(self, status: "Status | str", title: str) -> None:
        """输出分组标题（按组着色）。"""
        key = getattr(status, "value", status)
        self.line(self._colorize(str(title), _COLOR_BY_STATUS.get(str(key), "")))

    def flush(self) -> None:
        """刷新底层流。"""
        try:
            self.stream.flush()
        except Exception:
            pass

    # ---------------------------------------------------------------- 进度行
    def progress(self, text: str) -> None:
        """原地刷新一行进度（用回车回到行首，并清掉上一次的残留字符）。

        非 TTY（重定向/管道）下**不画进度行**：回车会污染文件内容，
        这种情况由调用方改成每 20% 打印一行（PRD §5.5）。
        """
        if self.quiet or not self.is_tty:
            return
        visible = truncate(text, self.width)
        padding = " " * max(0, self._progress_len - display_width(visible))
        self._write("\r" + visible + padding)
        self._progress_len = display_width(visible)

    def clear_progress(self) -> None:
        """清掉进度行，避免残留在报告上方。"""
        if self._progress_len <= 0:
            return
        self._write("\r" + " " * self._progress_len + "\r")
        self._progress_len = 0

    # ---------------------------------------------------------------- 内部
    def colorize(self, text: str, code: str) -> str:
        """按 ANSI 色号着色（color 关闭时原样返回）。"""
        return self._colorize(text, code)

    def _colorize(self, text: str, code: str) -> str:
        if not self.color_enabled or not code:
            return text
        return "\x1b[" + code + "m" + text + _COLOR_RESET

    def _write(self, text: str) -> None:
        try:
            self.stream.write(text)
            self.stream.flush()
        except Exception:
            pass


def debug_note(console: "Console", key: str, **kw: object) -> None:
    """在 --debug 下才打印的一行调试信息。"""
    console.line(t(key, **kw))


__all__ = [
    "Console", "init_terminal_encoding", "enable_windows_vt", "resolve_width",
    "display_width", "truncate", "pad", "debug_note",
    "console_attached", "ensure_console_streams", "pause_before_exit",
    "SYMBOL_READY", "SYMBOL_DEGRADED", "SYMBOL_PRERELEASE", "SYMBOL_BLOCKED",
    "SYMBOL_UNKNOWN", "SYMBOL_IGNORED",
]
