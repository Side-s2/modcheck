# -*- coding: utf-8 -*-
"""验证：GUI 勾选「同时下载测试性模组」确实改变计划，且默认不变。"""
import sys, tempfile
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))
cfg = Path(tempfile.mkdtemp(prefix="pre-")); tgt = Path(tempfile.mkdtemp(prefix="t-"))
from modcheck.gui.backend import CliBackend
be = CliBackend(config_dir=cfg)
be.save_scan(be.scan([ROOT / "mods_sample"]), "s")
be.run("s", "26.3", "Fabric", lambda *a: None, lambda: False)
r = be.last_report
from collections import Counter
print("报告状态分布:", dict(Counter(i.status.value for i in r.iter_items())))

a = be.prepare_download(r, tgt)
b = be.prepare_download(r, tgt, include_prerelease=True)
print(f"\n默认（不勾选）:  {len(a.plan.items)} 个")
print(f"勾选后        :  {len(b.plan.items)} 个")
extra = len(b.plan.items) - len(a.plan.items)
print(f"多出 {extra} 个 —— 与 🟠 的 4 个{'一致 ✅' if extra == 4 else '不一致 ❌'}")

# 确认多出来的确实是 🟠，且版本来自测试版通道
names_a = {i.target.name for i in a.plan.items}
for it in b.plan.items:
    if it.target.name not in names_a:
        vt = getattr(it.version, "version_type", "?")
        print(f"  新增: {it.entry.display_name:24s} {it.version.version_number:28s} 通道={vt}")
print("\n默认口径是否被改坏:", "✅ 未变" if len(a.plan.items) == 20 else f"⚠ 变成 {len(a.plan.items)}")
