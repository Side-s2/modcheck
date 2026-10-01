# -*- coding: utf-8 -*-
"""Linux/Windows 兼容性静态审计：找出平台专属 API 与硬编码路径分隔符，检查是否都有分支保护。"""
import ast, re, sys
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker") / "src"

SUSPECT_API = {
    "ctypes.windll": "Windows 专属", "winreg": "Windows 专属", "msvcrt": "Windows 专属",
    "os.startfile": "Windows 专属", "subprocess.CREATE_NO_WINDOW": "Windows 专属",
    "shutil.get_terminal_size": "跨平台（需 fallback）",
    "os.system": "需谨慎", "pwd": "Unix 专属", "grp": "Unix 专属", "termios": "Unix 专属",
    "fcntl": "Unix 专属", "resource": "Unix 专属",
}
PLATFORM_GUARDS = ("sys.platform", "os.name", "platform.system", "is_windows", "win32")

problems, notes = [], []
for path in sorted(ROOT.rglob("*.py")):
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    rel = path.relative_to(ROOT.parent)
    # 1) 平台专属 API 是否在 sys.platform 分支内
    for i, line in enumerate(lines, 1):
        for api, kind in SUSPECT_API.items():
            if api not in line or line.lstrip().startswith("#"):
                continue
            window = "\n".join(lines[max(0, i-12):i+3])
            guarded = any(g in window for g in PLATFORM_GUARDS)
            (notes if guarded else problems).append(
                f"{rel}:{i} [{kind}] {api}  -> {'有分支保护' if guarded else '**未发现平台分支**'}")
    # 2) 硬编码反斜杠路径（排除转义字符与正则）
    for i, line in enumerate(lines, 1):
        if re.search(r'"\\\\\\\\[A-Za-z]', line) and "re." not in line and "#" not in line.split("//")[0][:2]:
            notes.append(f"{rel}:{i} 疑似硬编码 Windows 路径: {line.strip()[:70]}")
    # 3) 文件编码是否都显式
    for i, line in enumerate(lines, 1):
        if re.search(r"\bopen\(|read_text\(|write_text\(", line) and "encoding" not in line:
            if "handle.open" in line or "target.open" in line:
                continue
            notes.append(f"{rel}:{i} 可能缺 encoding: {line.strip()[:70]}")

print("=" * 96)
print("平台专属 API 使用情况")
print("=" * 96)
if problems:
    print("  ⚠ 未发现平台分支的调用：")
    for p in problems:
        print("    " + p)
else:
    print("  ✅ 所有平台专属 API 调用都在 sys.platform / os.name 分支内")
print()
print(f"  有保护或被允许的调用（{len(notes)} 条，只列前 12 条）：")
for n in notes[:12]:
    print("    " + n)
print()
print("=" * 96)
print("POSIX 导入（如 termios/fcntl/pwd）—— 在 Windows 上会 ImportError")
print("=" * 96)
bad = []
for path in sorted(ROOT.rglob("*.py")):
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if re.match(r"\s*(import|from)\s+(termios|fcntl|pwd|grp|resource)\b", line):
            ctx = path.read_text(encoding="utf-8")
            if "sys.platform" not in ctx and "try:" not in ctx:
                bad.append(f"{path.relative_to(ROOT.parent)}:{i} {line.strip()}")
print("  " + ("✅ 没有裸导入 POSIX 模块" if not bad else "⚠ " + "; ".join(bad)))
