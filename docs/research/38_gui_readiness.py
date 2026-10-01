# -*- coding: utf-8 -*-
"""为 GUI 规划做的结构测量：现有"流程"代码里，多少是纯逻辑、多少是终端渲染。"""
import ast
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker") / "src" / "modcheck"

IO_NAMES = {"console", "print", "input", "t"}   # t() 是取文案，GUI 未必复用

def analyse(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    total = len([l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()])
    io_lines, pure_lines = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            if name in IO_NAMES or (isinstance(f, ast.Attribute)
                                    and isinstance(f.value, ast.Name) and f.value.id == "console"):
                for ln in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                    io_lines.add(ln)
    return total, len(io_lines)

print("=" * 88)
print("cli/commands/ 各文件：总行数 vs 直接做终端 IO 的行数")
print("=" * 88)
for p in sorted((ROOT / "cli" / "commands").glob("*.py")):
    total, io = analyse(p)
    pct = (io / total * 100) if total else 0
    print(f"  {p.name:16s} 总 {total:4d} 行 ｜ 终端 IO {io:4d} 行（{pct:4.0f}%）")

print()
print("=" * 88)
print("已就绪的 core 纯逻辑模块（GUI 可直接复用）")
print("=" * 88)
for p in sorted((ROOT / "core").glob("*.py")):
    src = p.read_text(encoding="utf-8")
    fn = src.count("\ndef ")
    print(f"  core/{p.name:18s} {len(src.splitlines()):4d} 行 ｜ {fn:2d} 个顶层函数")

print()
print("=" * 88)
print("结论")
print("=" * 88)
print("  core/ 里的判定与数据逻辑可直接被 GUI 复用；")
print("  但 cli/commands/ 里的**流程编排**（扫描->识别->存清单、检查->出报告）与终端输出绑在一起，")
print("  GUI 若直接复用会连带把终端渲染也拖进来。")
