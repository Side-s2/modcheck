# -*- coding: utf-8 -*-
"""精确判定 Ctrl+C 语义：不依赖 Windows 控制台事件，直接在进程内注入 KeyboardInterrupt。
这样测的是程序自己的 D11 处理逻辑（PRD 要求：输出已完成部分 + 退出码 130 + 无 traceback）。
"""
import io, os, sys, tempfile, threading, time, contextlib
from pathlib import Path

ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))
cfg = Path(tempfile.mkdtemp(prefix="kb-"))
os.environ["PYTHONIOENCODING"] = "utf-8"

from modcheck.cli.main import main as cli_main
import modcheck.providers.http as httpmod

# 先建清单（正常路径）
with contextlib.redirect_stdout(io.StringIO()):
    cli_main(["--config-dir", str(cfg), "scan", str(ROOT/"mods_sample"), "--profile", "s", "--yes"])

# 让检查跑到一半时抛出 KeyboardInterrupt —— 包装 transport，在第 N 次请求时触发
count = {"n": 0}
orig_init = httpmod.HttpClient.__init__

def patched_init(self, *a, **kw):
    orig_init(self, *a, **kw)
    real = self._transport          # 实例属性（我上一版误写成类属性）

    def _send(method, url, headers, data, timeout):
        count["n"] += 1
        if count["n"] >= 5:
            raise KeyboardInterrupt()
        return real(method, url, headers, data, timeout)

    self._transport = _send

httpmod.HttpClient.__init__ = patched_init

buf = io.StringIO()
code = None
try:
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = cli_main(["--config-dir", str(cfg), "check", "--profile", "s",
                         "--mc", "26.3", "--loader", "fabric", "--no-color", "--refresh"])
except KeyboardInterrupt:
    print("  ✗ KeyboardInterrupt 冒泡到调用方（未被捕获）")
except BaseException as e:
    print(f"  ✗ 抛出未处理的 {type(e).__name__}: {e}")

out = buf.getvalue()
print("=" * 88)
print(f"返回码 = {code}   （PRD D11 期望 130）")
print(f"含 Traceback = {'Traceback' in out}   （必须 False）")
lines = [l for l in out.splitlines() if l.strip()]
print(f"输出行数 = {len(lines)}")
print("输出尾部：")
for l in lines[-8:]:
    print("  |" + l[:104])
import shutil; shutil.rmtree(cfg, ignore_errors=True)
