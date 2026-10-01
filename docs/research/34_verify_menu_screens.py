# -*- coding: utf-8 -*-
"""独立验证 R2-11 交互三屏（选清单 -> 选版本 -> 选加载器 -> 确认页）。
非 TTY 下菜单被拒绝，所以只能进程内注入 input_fn —— 这也是主 Agent 的验收盲区。"""
import io, os, sys, tempfile, contextlib, re
from pathlib import Path

ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))
cfg = Path(tempfile.mkdtemp(prefix="menu3-"))

from modcheck.cli.main import build_parser, apply_menu_defaults, main as cli_main
from modcheck.cli import menu as menu_mod

# 建清单
with contextlib.redirect_stdout(io.StringIO()):
    cli_main(["--config-dir", str(cfg), "scan", str(ROOT/"mods_sample"), "--profile", "real", "--yes"])

parser = build_parser()
ns = parser.parse_args(["--config-dir", str(cfg)])
apply_menu_defaults(ns, parser)

# 脚本化输入：1=检查, 1=选第一个清单, 然后版本/加载器/确认，最后退出
# R2-11 后：版本屏是编号菜单（或 m 手动输入），加载器屏同理，之后是确认页。
# 我第一版按旧行为喂了自由文本 "26.3"，被正确拒绝（「没有这个选项」）—— 那是实现对了、我测错了。
answers = iter(["1", "1", "m", "26.3", "1", "y", "0"])
asked: list[str] = []

def input_fn(prompt: str) -> str:
    asked.append(prompt.strip())
    try:
        v = next(answers)
    except StopIteration:
        raise EOFError
    return v

buf = io.StringIO()
code = None
try:
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = menu_mod.run_menu(ns, input_fn=input_fn, console=None, ctx=None)
except SystemExit as e:
    code = e.code
except BaseException as e:
    print(f"  ✗ {type(e).__name__}: {e}")

out = buf.getvalue()
print("=" * 92)
print(f"返回码 = {code}")
print(f"含 Traceback = {'Traceback' in out}")
print()
print("被问到的提示语（按顺序）：")
for q in asked:
    print(f"  · {q[:88]}")
print()
checks = {
    "第1屏 选清单": bool(re.search(r"\[1\].*real|real.*30", out)),
    "第2屏 选版本": any("版本" in q for q in asked),
    "第3屏 选加载器": any("加载器" in q or "loader" in q.lower() for q in asked),
    "确认页": bool(re.search(r"确认|将检查|预计", out)),
}
print("三屏 + 确认页检查：")
for k, v in checks.items():
    print(f"  {'✅' if v else '❌'} {k}")
print()
print("输出尾部：")
for l in [x for x in out.splitlines() if x.strip()][-12:]:
    print("  |" + l[:100])
import shutil; shutil.rmtree(cfg, ignore_errors=True)
