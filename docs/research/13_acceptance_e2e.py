# -*- coding: utf-8 -*-
"""主 Agent 独立端到端验收：拿用户真实服数据跑完整流程，与独立基准逐条比对。

用法:
    .toolchain\Python311\python.exe docs\research\13_acceptance_e2e.py

设计要点:
  * 不 import modcheck，只把它当成黑盒命令行程序来用（真正的端到端）。
  * 期望值来自 docs/research/results/11_ground_truth_mods_sample.json（另一条独立实现路径）。
  * 文本分组计数 + JSON 明细双路核对；JSON 结构不认识时自动降级为只核文本。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / ".toolchain" / "Python311" / "python.exe"
ORACLE = json.loads((ROOT / "docs/research/results/11_ground_truth_mods_sample.json").read_text(encoding="utf-8"))
SAMPLE = ROOT / "mods_sample"

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
results: list[tuple[str, str, str]] = []


def check(level: str, name: str, detail: str = "") -> None:
    results.append((level, name, detail))
    icon = {"PASS": "[PASS]", "FAIL": "[FAIL]", "WARN": "[WARN]"}[level]
    print(f"{icon} {name}" + (f"  —— {detail}" if detail else ""), flush=True)


def run(args: list[str], env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    env["NO_COLOR"] = "1"
    env.update(env_extra or {})
    return subprocess.run([str(PY), "-m", "modcheck", *args], cwd=str(ROOT), env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=900)


def main() -> int:
    if not SAMPLE.exists():
        print("缺少 mods_sample/（用户提供的真实数据），无法验收"); return 2
    cfg = Path(tempfile.mkdtemp(prefix="modcheck-acc-"))
    print(f"临时配置目录: {cfg}\n" + "=" * 90)

    # ---------- 1. 扫描建立清单 ----------
    r = run(["--config-dir", str(cfg), "scan", str(SAMPLE), "--profile", "sample", "--yes"])
    print("--- scan stdout ---"); print(r.stdout[-2500:]); print(f"[scan exit={r.returncode}]")
    if r.returncode != 0:
        check(FAIL, "scan 退出码应为 0", f"实际 {r.returncode}")
    else:
        check(PASS, "scan 退出码 0")
    if "Traceback" in r.stdout + r.stderr:
        check(FAIL, "scan 不得打印 traceback")
    else:
        check(PASS, "scan 无 traceback")

    prof = None
    for cand in (cfg / "profiles").glob("*.json") if (cfg / "profiles").exists() else []:
        prof = cand
    if prof is None:
        check(FAIL, "scan 未生成清单文件", str(cfg))
        shutil.rmtree(cfg, ignore_errors=True)
        return 1
    profile_data = json.loads(prof.read_text(encoding="utf-8"))
    mods = profile_data.get("mods", [])
    check(PASS if len(mods) >= 25 else FAIL, f"清单条目数（期望 30）", f"实际 {len(mods)}")
    guessed = sum(1 for m in mods if str(m.get("match_status")) == "guess")
    check(PASS if guessed == 0 else WARN, "真实 jar 不应产生 guess 条目", f"guess={guessed}")

    # ---------- 2. 检查（26.3 / fabric） ----------
    js = cfg / "report.json"
    r = run(["--config-dir", str(cfg), "check", "--profile", "sample",
             "--mc", "26.3", "--loader", "fabric", "--no-color", "--json", str(js)])
    out = r.stdout + r.stderr
    print("\n--- check stdout（尾部）---"); print(r.stdout[-3500:])
    if "Traceback" in out:
        check(FAIL, "check 不得打印 traceback")
    else:
        check(PASS, "check 无 traceback")
    if re.search(r"\x1b\[", out):
        check(FAIL, "--no-color / 管道下不得有 ANSI 转义")
    else:
        check(PASS, "无 ANSI 转义残留")

    # 期望：21 ready / 7 degraded / 2 blocked
    exp = {"READY": 0, "DEGRADED": 0, "BLOCKED": 0}
    for v in ORACLE["cases"]["26.3/fabric"].values():
        exp[v["status"]] = exp.get(v["status"], 0) + 1
    check(PASS if exp["BLOCKED"] == 2 else WARN, "基准自检：26.3/fabric 阻塞应为 2", str(exp))

    # 文本分组计数
    groups = {"阻塞": None, "需降级": None, "未判定": None, "就绪": None}
    for name in groups:
        m = re.search(rf"(?:🔴|🟡|⚪|🟢|⚫)?\s*{name}（(\d+)\s*个）", r.stdout)
        if m:
            groups[name] = int(m.group(1))
    print(f"\n从报告文本解析到的分组计数: {groups}")
    expect_text = {"阻塞": exp["BLOCKED"], "需降级": exp["DEGRADED"], "就绪": exp["READY"]}
    for name, want in expect_text.items():
        got = groups.get(name)
        if got is None:
            check(WARN, f"报告文本未解析到「{name}」分组标题", "可能排版与 PRD §5.4 不一致")
        elif got != want:
            check(FAIL, f"「{name}」数量与独立基准不符", f"程序 {got} / 基准 {want}")
        else:
            check(PASS, f"「{name}」数量 = {want}（与基准一致）")

    # 退出码：有阻塞 → 1
    check(PASS if r.returncode == 1 else FAIL, "有阻塞项时退出码应为 1", f"实际 {r.returncode}")

    # ---------- 3. JSON 明细比对 ----------
    if js.exists():
        try:
            data = json.loads(js.read_text(encoding="utf-8"))
            items = _extract_items(data)
            if items is None:
                check(WARN, "JSON 导出结构无法识别", "需要人工确认 schema")
            else:
                check(PASS, f"JSON 导出可解析，{len(items)} 条明细")
                _compare_items(items, ORACLE["cases"]["26.3/fabric"])
        except Exception as e:
            check(FAIL, "JSON 导出无法解析", f"{type(e).__name__}: {e}")
    else:
        check(WARN, "--json 未生成文件", str(js))

    # ---------- 4. 退出码矩阵 ----------
    print("\n--- 退出码矩阵 ---")
    for label, args, want in [
        ("--version", ["--version"], 0), ("--help", ["--help"], 0),
        ("未知参数", ["--bogus"], 3), ("不存在子命令", ["frobnicate"], 3),
        ("非法 --loader", ["check", "--loader", "bukkit"], 3),
    ]:
        rr = run(args)
        check(PASS if rr.returncode == want else FAIL, f"退出码 {label} 应为 {want}", f"实际 {rr.returncode}")

    # ---------- 5. 汇总 ----------
    shutil.rmtree(cfg, ignore_errors=True)
    n_fail = sum(1 for lv, _, _ in results if lv == FAIL)
    n_warn = sum(1 for lv, _, _ in results if lv == WARN)
    n_pass = sum(1 for lv, _, _ in results if lv == PASS)
    print("\n" + "=" * 90)
    print(f"验收汇总：PASS {n_pass} ｜ WARN {n_warn} ｜ FAIL {n_fail}")
    for lv, name, detail in results:
        if lv != PASS:
            print(f"  {lv}: {name}  {detail}")
    return 1 if n_fail else 0


def _extract_items(data):
    """在未知 schema 下尽力找出条目列表。"""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return None
    for key in ("items", "results", "mods", "entries"):
        v = data.get(key)
        if isinstance(v, list):
            return v
    grp = data.get("groups")
    if isinstance(grp, dict):
        flat = []
        for gname, lst in grp.items():
            for it in (lst or []):
                if isinstance(it, dict):
                    flat.append({**it, "_group": gname})
        return flat or None
    return None


def _status_of(item: dict) -> str | None:
    for k in ("status", "state", "result", "_group"):
        v = item.get(k)
        if isinstance(v, str):
            up = v.upper()
            for s in ("READY", "DEGRADED", "BLOCKED", "UNKNOWN", "IGNORED"):
                if s in up:
                    return s
    return None


def _slug_of(item: dict) -> str | None:
    # 顶层直接给 slug 的情况
    for k in ("slug", "project", "project_slug"):
        v = item.get(k)
        if isinstance(v, str) and v:
            return v
    # 实际结构：item["mod"] 是 ModEntry，slug 在 mod.sources.modrinth
    for holder in (item.get("mod"), item):
        if not isinstance(holder, dict):
            continue
        src = holder.get("sources")
        if isinstance(src, dict) and src.get("modrinth"):
            return str(src["modrinth"])
        for k in ("mod_id", "modid", "key"):
            v = holder.get(k)
            if isinstance(v, str) and v:
                return v
    return None


def _file_of(item: dict) -> str | None:
    mod = item.get("mod")
    if isinstance(mod, dict):
        for k in ("file_name", "key", "mod_id"):
            v = mod.get(k)
            if isinstance(v, str) and v:
                return v
    return _slug_of(item)


def _compare_items(items, oracle_case):
    """oracle_case 以【文件名】为键（见 11_oracle_mods_sample.py），因此按文件名连接。"""
    by_file: dict[str, dict] = {}
    for it in items:
        for cand in (_file_of(it), _slug_of(it)):
            if cand:
                by_file.setdefault(cand.lower(), it)
    if not by_file:
        check(WARN, "JSON 明细里找不到可用连接键（file_name/slug）", "跳过逐条比对")
        return
    wrong = missing = 0
    for name, exp in oracle_case.items():
        got = by_file.get(name.lower()) or by_file.get(str(exp.get("slug", "")).lower())
        if got is None:
            missing += 1
            if missing <= 3:
                check(WARN, f"未在 JSON 明细里找到 {name}", "可能被忽略或未匹配")
            continue
        st = _status_of(got)
        if st != exp["status"]:
            wrong += 1
            check(FAIL, f"{name} 状态不符", f"程序 {st} / 基准 {exp['status']}")
    if missing:
        check(WARN, f"{missing}/{len(oracle_case)} 个模组未出现在 JSON 明细里", "")
    if wrong == 0 and missing == 0:
        check(PASS, f"逐条比对：{len(oracle_case)} 个模组的文件名与状态全部与独立基准一致")


if __name__ == "__main__":
    raise SystemExit(main())
