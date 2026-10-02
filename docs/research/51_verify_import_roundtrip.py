# -*- coding: utf-8 -*-
"""往返验证：导出清单 -> 在全新配置目录里导入 -> 内容必须一致。"""
import sys, tempfile
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))
from modcheck.gui.backend import CliBackend
from modcheck.flows.export import export_modlist, modlist_filename

# A 服主：扫描并导出
cfg_a = Path(tempfile.mkdtemp(prefix="a-"))
be_a = CliBackend(config_dir=cfg_a)
be_a.save_scan(be_a.scan([ROOT / "mods_sample"]), "生存服")
prof_a = be_a.load_profile("生存服")
out = Path(tempfile.mkdtemp()) / modlist_filename("生存服", "json")
export_modlist(prof_a, out, fmt="json")
print(f"A 导出：{len(prof_a.mods)} 个模组 -> {out.name}")

# B 服主：全新环境里导入
cfg_b = Path(tempfile.mkdtemp(prefix="b-"))
be_b = CliBackend(config_dir=cfg_b)
print("B 导入前清单:", be_b.profiles())
res = be_b.import_modlist_file(out)
print("B 导入后清单:", be_b.profiles())

prof_b = be_b.load_profile("生存服")
names_a = sorted((m.file_name or m.key) for m in prof_a.mods)
names_b = sorted((m.file_name or m.key) for m in prof_b.mods)
print(f"\nA 有 {len(names_a)} 个，B 有 {len(names_b)} 个")
print("逐条一致:", "✅" if names_a == names_b else f"❌ 差异: {set(names_a) ^ set(names_b)}")

# 再导入一次（幂等）
r2 = be_b.import_modlist_file(out)
print(f"重复导入后仍有 {len(be_b.load_profile('生存服').mods)} 个 ->", "✅ 幂等" if len(be_b.load_profile('生存服').mods) == len(names_a) else "❌ 重复了")

# 非法文件
bad = Path(tempfile.mkdtemp()) / "bad.json"
bad.write_text('{"schema_version": 1, "mods": [{"file_name": 26}]}', encoding="utf-8")
try:
    be_b.import_modlist_file(bad)
    print("非法文件: ❌ 竟然通过了")
except Exception as exc:
    print(f"非法文件被拒绝: ✅ {str(exc)[:60]}")
