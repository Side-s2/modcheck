"""R2-4：源码里引用的每个 i18n key 都必须能解析（半成品感的根源之一）。

把"缺文案直接把 key 名喷给用户"变成**测试期硬约束**，和 AST 回归一个思路。
"""
from __future__ import annotations

import re
from pathlib import Path

from modcheck import i18n

SRC = Path(__file__).resolve().parent.parent / "src" / "modcheck"
#: t("key") / tn("key", n) 的直接字面量调用
_KEY_RE = re.compile(r'\bt[n]?\(\s*"([a-z0-9_.]+)"')
#: 动态拼接的前缀：t("group." + status.value + ".title")
_PREFIX_RE = re.compile(r'\bt[n]?\(\s*"([a-z0-9_.]*\.)"\s*\+')


def _files() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if p.name != "i18n.py"]


def test_every_referenced_key_exists() -> None:
    """所有直接引用的 key 都必须存在。"""
    missing: list[str] = []
    for path in _files():
        for match in _KEY_RE.finditer(path.read_text(encoding="utf-8")):
            key = match.group(1)
            if key.endswith("."):
                continue  # 动态拼接，交给下面那条
            if not i18n.has(key):
                missing.append(f"{path.name}: {key}")
    assert missing == [], "引用了不存在的 i18n key:\n" + "\n".join(missing)


def test_dynamic_prefixes_have_keys() -> None:
    """动态拼接的前缀（如 group. / status. / source.）必须至少有一个真实 key。"""
    broken: list[str] = []
    for path in _files():
        for match in _PREFIX_RE.finditer(path.read_text(encoding="utf-8")):
            prefix = match.group(1)
            if not any(key.startswith(prefix) for key in i18n.keys()):
                broken.append(f"{path.name}: {prefix}")
    assert broken == [], "动态拼接的前缀没有对应 key：\n" + "\n".join(broken)
