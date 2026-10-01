"""交互询问封装（可注入假输入，便于测试整条交互路径）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from modcheck.console import Console
from modcheck.errors import UserCancelled
from modcheck.i18n import t


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
        self.out = out

    def ask(self, prompt: str) -> str:
        """问一句并返回原始输入（EOF/Ctrl+C 当作取消）。

        用户敲完回车后统一空两行再继续输出 —— 否则后续内容会紧贴着他刚敲的字，
        信息密集的检查报告尤其难读（用户要求）。
        """
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


__all__ = ["Choice", "Prompter"]
