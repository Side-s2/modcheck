# -*- coding: utf-8 -*-
"""重构前的 CLI 输出快照：重构后必须逐字一致（离网可复现的那部分）。"""
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
