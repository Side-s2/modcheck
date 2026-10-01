"""分层硬约束的自动化版本：flows/ 不许打印、不许退出、不许依赖 cli。

与 docs/research/36_layering_check.py 同一套规则，区别是它在每个 pytest 里跑：
流程层一旦沾上终端输出，GUI 就没法复用它（docs/GUI_DESIGN.md §1 验收标准 2）。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "modcheck"
FLOWS = SRC / "flows"

BAD_IMPORTS = ("modcheck.cli",)
BAD_CALLS = {"print", "input", "exit", "quit"}
BAD_ATTRS = {("sys", "exit"), ("os", "system")}


def flow_modules() -> list[Path]:
    """flows/ 下的全部模块（至少要有 3 个，防止路径写错后"零违规"假通过）。"""
    return sorted(FLOWS.rglob("*.py"))


#: 这几个模块必须存在 —— 少一个就说明流程层被搬走或改名了
REQUIRED_MODULES = ("__init__.py", "check_flow.py", "scan_flow.py")


def test_flows_package_exists() -> None:
    """flows 包必须真的在，且必需的模块一个都不能少。

    ⚠️ 这里**不再断言"目录内容恰好等于某个清单"**：
    主 Agent 后来加了 runtime.py（CLI 与 GUI 共用的依赖装配），
    精确匹配的写法立刻误报 —— 那种断言把"合理新增"和"模块丢失"混为一谈了。
    现在只保证"必需的都在"，新增模块由下面的逐模块 AST 检查兜底。
    """
    names = {p.name for p in flow_modules()}
    missing = [name for name in REQUIRED_MODULES if name not in names]
    assert not missing, f"flows/ 缺少必需模块：{missing}"


@pytest.mark.parametrize("path", flow_modules(), ids=lambda p: p.name)
def test_flows_has_no_terminal_io_or_cli_dependency(path: Path) -> None:
    """逐模块 AST 检查：没有 print/input/sys.exit，也没有 import modcheck.cli。"""
    problems: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            problems += [f"import {a.name}" for a in node.names
                         if a.name.startswith(BAD_IMPORTS)]
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").startswith(BAD_IMPORTS):
                problems.append(f"from {node.module}")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in BAD_CALLS:
                problems.append(f"调用 {func.id}()")
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) \
                    and (func.value.id, func.attr) in BAD_ATTRS:
                problems.append(f"调用 {func.value.id}.{func.attr}()")
    assert problems == [], f"{path.name} 违反流程层约束：" + "、".join(problems)


def test_flows_exposes_progress_and_cancel_hooks() -> None:
    """进度与取消必须是参数（回调/探针），不能藏在全局里。"""
    import inspect

    from modcheck.flows import run_check_flow, scan_dirs

    for func in (scan_dirs, run_check_flow):
        params = inspect.signature(func).parameters
        assert "on_progress" in params, func.__name__
        assert "should_stop" in params, func.__name__
