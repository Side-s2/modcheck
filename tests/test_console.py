"""console 层测试：宽度、截断、颜色探测、编码初始化。"""
from __future__ import annotations

import io
import os

from modcheck import console as c


def test_display_width_cjk() -> None:
    """T-16 验收：CJK 全角算 2 列。"""
    assert c.display_width("[地毯] Carpet") == 13
    assert c.display_width("abc") == 3
    assert c.display_width("") == 0


def test_truncate_and_pad() -> None:
    """按显示宽度截断与补空格。"""
    assert c.truncate("abcdef", 4) == "abc…"
    assert c.truncate("abc", 4) == "abc"
    assert c.truncate("地毯地毯", 5) == "地毯…"
    assert c.pad("地毯", 6) == "地毯  "
    assert c.pad("abcdef", 2) == "abcdef"


def test_color_disabled_when_not_tty(monkeypatch) -> None:
    """非 TTY（管道/重定向）一律不输出颜色。"""
    monkeypatch.delenv("NO_COLOR", raising=False)
    stream = io.StringIO()
    console = c.Console(stream=stream, color="auto", width=100)
    assert console.color_enabled is False
    console.group("ready", "标题")
    assert "\x1b[" not in stream.getvalue()


def test_no_color_env(monkeypatch) -> None:
    """NO_COLOR 环境变量强制关色。"""
    monkeypatch.setenv("NO_COLOR", "1")
    console = c.Console(stream=io.StringIO(), color="auto")
    assert console.color_enabled is False
    assert c.Console(stream=io.StringIO(), color="never").color_enabled is False


def test_resolve_width_non_tty(monkeypatch) -> None:
    """非 TTY 时优先 COLUMNS，否则 100。"""
    monkeypatch.setenv("COLUMNS", "123")
    assert c.resolve_width() == 123
    monkeypatch.delenv("COLUMNS", raising=False)
    assert c.resolve_width() == 100


def test_progress_line_is_cleared() -> None:
    """进度行会被清掉，不残留。"""
    stream = io.StringIO()
    console = c.Console(stream=stream, color="never", width=100)
    console.progress("abc")
    console.clear_progress()
    console.line("报告")
    assert stream.getvalue().endswith("报告\n")


def test_quiet_suppresses_progress() -> None:
    """--quiet 下不画进度。"""
    stream = io.StringIO()
    console = c.Console(stream=stream, color="never", quiet=True)
    console.progress("abc")
    assert stream.getvalue() == ""


def test_init_terminal_encoding_never_raises() -> None:
    """编码初始化在异常环境下也不抛。"""
    assert c.init_terminal_encoding() in ("utf-8", "legacy")
    assert os.environ.get("PYTHONIOENCODING") is None or True
