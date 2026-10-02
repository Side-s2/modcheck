# -*- coding: utf-8 -*-
"""CLI 输出快照（离网可复现的那部分）。

用法：直接运行本脚本即可**重新生成** docs/research/golden/ 下的全部快照文件
（脚本没有 compare 模式，比较用 git diff）。

基线更新记录：
  · 文案规范化：全部面向用户的文案由口语化改写为书面表达（src/modcheck/i18n.py 共 150 条），
    本次快照**整体重新生成**。与上一版逐字不一致属于**预期**，不是回归：
    差异只应出现在描述性文字上；退出码、命令、分组、列序、列宽与缩进结构均不应变化。
    复核时请用 git diff -- docs/research/golden 逐条确认改动仅为措辞。
  · 其中 config_show / profile_list / cache_info 三个 stdout 含临时配置目录名，
    它们的差异天然不可复现，属正常噪声。
"""
import json, os, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
PY = ROOT / ".toolchain" / "Python311" / "python.exe"
OUT = ROOT / "docs" / "research" / "golden"
OUT.mkdir(parents=True, exist_ok=True)
cfg = Path(tempfile.mkdtemp(prefix="golden-"))
env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8", NO_COLOR="1")

def run(*args, stdin=""):
    p = subprocess.run([str(PY), "-m", "modcheck", "--config-dir", str(cfg), *args],
                       cwd=str(ROOT), env=env, input=stdin, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=180)
    return p.returncode, p.stdout, p.stderr

# 造一份离线可复现的清单（不联网：直接写文件）
(cfg / "profiles").mkdir(parents=True, exist_ok=True)
(cfg / "profiles" / "demo.json").write_text(json.dumps({
    "schema_version": 1, "name": "demo", "description": "", "created_at": "", "updated_at": "",
    "mods": [{"key": "slug:modrinth:carpet", "display_name": "Carpet", "mod_id": "carpet",
              "file_name": "carpet-26.1.jar", "sources": {"modrinth": "carpet"}, "detected": {},
              "match_status": "exact", "notes": "", "added_at": "", "updated_at": ""},
             {"key": "unknown-thing", "display_name": "UnknownThing", "mod_id": None,
              "file_name": "unknown-thing-1.0.jar", "sources": {}, "detected": {},
              "match_status": "unmatched", "notes": "", "added_at": "", "updated_at": ""}]},
    ensure_ascii=False), encoding="utf-8")

CASES = [
    ("version", ["--version"]),
    ("help", ["--help"]),
    ("profile_list", ["profile", "list"]),
    ("profile_show", ["profile", "show", "demo"]),
    ("config_show", ["config", "show"]),
    ("cache_info", ["cache", "info"]),
    ("versions_help", ["versions", "--help"]),
    ("err_bogus_arg", ["--bogus"]),
    ("err_unknown_cmd", ["frobnicate"]),
    ("err_bad_loader", ["check", "--profile", "demo", "--mc", "26.3", "--loader", "quilt"]),
    ("err_no_profile", ["check", "--profile", "nope", "--mc", "26.3", "--loader", "fabric"]),
    ("err_missing_value", ["check", "--mc"]),
    ("menu_non_tty", [], "0\n"),
]

manifest = {}
for name, args, *rest in CASES:
    stdin = rest[0] if rest else ""
    code, out, err = run(*args, stdin=stdin)
    (OUT / (name + ".stdout.txt")).write_text(out, encoding="utf-8", newline="\n")
    (OUT / (name + ".stderr.txt")).write_text(err, encoding="utf-8", newline="\n")
    manifest[name] = {"args": args, "exit": code, "stdout_lines": len(out.splitlines())}
    print(f"  {name:18s} exit={code}  stdout {len(out.splitlines()):4d} 行")

(OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n快照已写入 {OUT.relative_to(ROOT)}（{len(CASES)} 个用例）")
import shutil; shutil.rmtree(cfg, ignore_errors=True)
