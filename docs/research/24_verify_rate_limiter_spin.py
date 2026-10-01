# -*- coding: utf-8 -*-
"""耗尽令牌后再 acquire —— 验证「假 clock 不前进 + no-op sleep」时是否永久自旋。"""
import sys, time
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))
from modcheck.providers.http import RateLimiter

frozen = [1000.0]
def clock(): return frozen[0]
sleeps = []
def sleep(s): sleeps.append(s)

rl = RateLimiter(5, clock=clock, sleep=sleep)
print(f"per_minute=5, 冻结时钟, no-op sleep", flush=True)
for i in range(1, 21):
    rl.acquire()
    print(f"  acquire #{i} 返回，累计 sleep 调用 {len(sleeps)} 次", flush=True)
print("全部 20 次都返回了 -> 不会永久自旋", flush=True)
