"""交互询问封装（可注入假输入，便于测试整条交互路径）。

三条硬约束（R3 任务书 §0）：
  1. input_fn 必须可注入 —— 所有屏幕测试都靠它，不依赖真实 TTY；
  2. **非交互终端绝不提问**：input_fn 没注入（即真的读 stdin）且 stdin 不是 TTY 时，
     直接抛 UserCancelled。否则在管道/重定向下会挂死等输入（实测风险）；
  3. 统一在这里做「输入后空两行」，别在每个屏幕里各写一遍。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable, Final, Sequence

from modcheck.console import Console
from modcheck.errors import UserCancelled
from modcheck.i18n import t

#: 一次输入点最多允许几次非法输入，超过就回上一层（PRD §13.4 第 3 条）
MAX_INVALID_TRIES: Final[int] = 3

#: read_line 的三种结果
KIND_OK: Final[str] = "ok"
KIND_BACK: Final[str] = "back"
KIND_QUIT: Final[str] = "quit"


def stdin_is_tty() -> bool:
    """标准输入是不是交互式终端（任何异常都当成"不是"）。"""
    try:
        return bool(sys.stdin is not None and sys.stdin.isatty())
    except Exception:
        return False


@dataclass(frozen=True, slots=True)
class Choice:
    """一个菜单选项。"""

    key: str
    label: str


class Prompter:
    """统一的输入门面；input_fn 可注入，测试里喂固定序列。"""

    def __init__(self, *, input_fn: Callable[[str], str] | None = None,
                 out: Console | None = None) -> None:
        self._input = input_fn or input
        #: 是否注入了假输入（只有真读 stdin 时才需要判 TTY，见 ask）
        self.injected = input_fn is not None
        self.out = out

    def ask(self, prompt: str) -> str:
        """问一句并返回原始输入（EOF/Ctrl+C 当作取消，非交互终端直接取消）。

        用户敲完回车后统一空两行再继续输出 —— 否则后续内容会紧贴着他刚敲的字，
        信息密集的检查报告尤其难读（用户要求）。
        """
        if not self.injected and not stdin_is_tty():
            # 管道/重定向里提问会挂死（等一个永远不来的输入），所以直接取消
            raise UserCancelled(t("menu.non_interactive"))
        try:
            raw = self._input(prompt)
        except (EOFError, KeyboardInterrupt) as exc:
            raise UserCancelled(t("menu.bye")) from exc
        if self.out is not None:
            self.out.line()
            self.out.line()
        return raw.strip()

    def choose(self, title: str, options: Sequence[Choice], *, allow_back: bool = False,
               default: str | None = None) -> str:
        """打印编号选项并返回用户选中的 key。

        抛出：
            UserCancelled: 输入 EOF 或 Ctrl+C（由调用方决定回哪一层）。
        """
        if self.out is not None:
            self.out.line(title)
            for index, option in enumerate(options, start=1):
                self.out.line(t("menu.title", index=index, label=option.label))
            if allow_back:
                self.out.line(t("menu.back"))
            self.out.line(t("menu.quit"))
        while True:
            raw = self.ask(t("menu.prompt"))
            if not raw and default is not None:
                return default
            if raw == "b" and allow_back:
                return "b"
            if raw == "q":
                return "q"
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                return options[int(raw) - 1].key
            if self.out is not None:
                self.out.line(t("menu.invalid_choice"))

    def confirm(self, question: str, *, default: bool = True) -> bool:
        """是/否询问（回车取默认值）。"""
        raw = self.ask(question).lower()
        if not raw:
            return default
        return raw in ("y", "yes")


def read_line(prompter: Prompter, prompt: str, *,
              allow_back: bool = True) -> tuple[str, str]:
    """读一行并识别 b / q（PRD §13.4：每个输入点都要有返回路径）。

    参数：
        prompter: 注入的询问器。
        prompt: 提示文本（行尾必须已经写明 [b] / [q]）。
        allow_back: 是否接受 b（列表屏用 q，输入屏 b 与 q 都接受）。
    返回：
        (KIND_OK, 文本) / (KIND_BACK, "") / (KIND_QUIT, "")。
    """
    raw = prompter.ask(prompt)
    low = raw.strip().lower()
    if allow_back and low == "b":
        return KIND_BACK, ""
    if low == "q":
        return KIND_QUIT, ""
    return KIND_OK, raw.strip()


__all__ = ["Choice", "Prompter", "read_line", "stdin_is_tty",
           "MAX_INVALID_TRIES", "KIND_OK", "KIND_BACK", "KIND_QUIT"]
