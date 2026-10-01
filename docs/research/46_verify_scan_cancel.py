# -*- coding: utf-8 -*-
"""验证：扫描第二阶段能被立刻取消，且结果标记为 cancelled（禁止落盘）。"""
import sys, time, tempfile
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))
cfg = Path(tempfile.mkdtemp(prefix="cancel-"))
from modcheck.gui.backend import CliBackend
be = CliBackend(config_dir=cfg)

state = {"cancel_at": None}
t0 = time.time()
def should_stop():
    if state["cancel_at"] is None:
        state["cancel_at"] = time.time()
        return False
    return time.time() - state["cancel_at"] > 2.0      # 2 秒后叫停

print("开始扫描，2 秒后请求取消……")
report = be.scan([ROOT / "mods_sample"], on_progress=lambda d, t, n: None,
                 should_stop=should_stop)
elapsed = time.time() - t0
print(f"  返回耗时: {elapsed:.1f} 秒")
print(f"  cancelled 标记: {report.cancelled}")
print(f"  识别条目: {len(report.entries)}")
if report.cancelled and elapsed < 30:
    print("  ✅ 取消能在几秒内生效（修复前这里会跑满几分钟）")
elif report.cancelled:
    print(f"  ⚠ 取消了，但花了 {elapsed:.0f} 秒 —— 取消仍然偏慢")
else:
    print("  ❌ 没有取消成功")
print()
print("  半份结果必须被禁止落盘：")
from modcheck.flows.scan_flow import save_scan_result
try:
    save_scan_result(report, profiles_dir=be.runtime.profiles_dir, profile_name="x")
    print("  ❌ 危：半份结果竟然落盘了")
except Exception as exc:
    print(f"  ✅ 落盘被拒绝: {type(exc).__name__}: {str(exc)[:70]}")
