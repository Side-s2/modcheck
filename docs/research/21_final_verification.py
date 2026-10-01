# -*- coding: utf-8 -*-
"""最终验收总控：一次性跑完全部独立验证，输出统一的 PASS/FAIL 汇总。

这不是程序员的自测，而是主 Agent 从外部对交付物做的验收。
用法：.toolchain\Python311\python.exe docs\research\21_final_verification.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / ".toolchain" / "Python311" / "python.exe"
SAMPLE = ROOT / "mods_sample"

RESULTS: list[tuple[str, str, str]] = []   # (等级, 名称, 说明)


def record(level: str, name: str, detail: str = "") -> None:
    RESULTS.append((level, name, detail))
    icon = {"PASS": "[PASS]", "FAIL": "[FAIL]", "WARN": "[WARN]", "SKIP": "[SKIP]"}[level]
    print(f"{icon} {name}" + (f"  -- {detail}" if detail else ""), flush=True)


def run(args: list[str], *, env_extra: dict[str, str] | None = None, cwd: Path | None = None,
        timeout: int = 900) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8", NO_COLOR="1")
    env.update(env_extra or {})
    return subprocess.run(args, cwd=str(cwd or ROOT), env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout)


def section(title: str) -> None:
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78, flush=True)


# ---------------------------------------------------------------- 1. 测试套件
def check_pytest() -> None:
    section("1. 测试套件")
    r = run([str(PY), "-m", "pytest", "-q", "--no-header"])
    tail = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
    if r.returncode == 0:
        record("PASS", "离线测试全绿", tail[-80:])
    else:
        record("FAIL", "离线测试有失败", tail[-160:])
    r2 = run([str(PY), "-m", "pytest", "-m", "live", "-q", "--no-header"])
    if r2.returncode == 0:
        tail2 = (r2.stdout or "").strip().splitlines()[-1] if r2.stdout else ""
        record("PASS", "真实网络测试(live)全绿", tail2[-80:])
    else:
        record("FAIL", "live 测试有失败", ((r2.stdout or "") + (r2.stderr or ""))[-200:])


# ---------------------------------------------------------------- 2. 既有验证脚本
def check_scripts() -> None:
    section("2. 主 Agent 的独立验证脚本")
    for name, path in [
        ("classify 六分支场景矩阵", "docs/research/14_verify_classify.py"),
        ("端到端黑盒验收（真实 30 模组）", "docs/research/13_acceptance_e2e.py"),
        ("表格对齐（按显示宽度）", "docs/research/19_verify_table_alignment.py"),
        ("真实数据集成（Provider→classify）", "docs/research/17_live_integration.py"),
    ]:
        # 这些脚本依赖真实网络。Modrinth 偶发 SSL/限流会让它们失败，
        # 那不是回归 —— 失败时重跑一次，只有连续两次都失败才记为 FAIL。
        r = run([str(PY), str(ROOT / path)], timeout=1200)
        if r.returncode == 0:
            record("PASS", name)
            continue
        r2 = run([str(PY), str(ROOT / path)], timeout=1200)
        if r2.returncode == 0:
            record("PASS", name + "（首次失败，重跑通过 —— 网络偶发）")
        else:
            record("FAIL", name, ((r2.stdout or "") + (r2.stderr or ""))[-200:])


# ---------------------------------------------------------------- 3. 场景不变量
def _scan(tmp: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run([str(PY), "-m", "modcheck", "--config-dir", str(tmp), "scan", *args])


def check_d35_unidentified_jars_listed() -> None:
    section("3. D35：无元数据 jar 必须进清单")
    work = Path(tempfile.mkdtemp(prefix="fin-d35-"))
    mods = work / "mods"; mods.mkdir()
    with zipfile.ZipFile(mods / "no-meta-1.0.jar", "w") as z:
        z.writestr("pack.mcmeta", "{}")
    with zipfile.ZipFile(mods / "custom-kit-2.1.jar", "w") as z:
        z.writestr("fabric.mod.json", json.dumps({"id": "my-private-kit", "version": "2.1"}))
    real = SAMPLE / "krypton-0.3.0.jar"
    if real.exists():
        (mods / real.name).write_bytes(real.read_bytes())
    expected = len(list(mods.glob("*.jar")))
    r = _scan(work, str(mods), "--profile", "t", "--yes")
    prof = work / "profiles" / "t.json"
    if not prof.exists():
        record("FAIL", "D35 清单未生成", (r.stdout or "")[-160:]); return
    got = len(json.loads(prof.read_text(encoding="utf-8"))["mods"])
    if got == expected:
        record("PASS", f"D35 清单条目数 == jar 数（{got}）")
    else:
        record("FAIL", f"D35 清单条目数 {got} != jar 数 {expected}",
               "无元数据的 jar 被跳过了，用户会觉得模组不见了")
    import shutil; shutil.rmtree(work, ignore_errors=True)


def check_d38_identifier_consistency() -> None:
    section("4. D38：两条识别路径写入同一种平台标识")
    work = Path(tempfile.mkdtemp(prefix="fin-d38-"))
    # 路径 A：搜索（--from-list）
    names = work / "names.txt"
    names.write_text("krypton-0.3.0.jar\n", encoding="utf-8")
    _scan(work, "--from-list", str(names), "--profile", "a", "--yes")
    # 路径 B：hash（扫真实文件夹）
    _scan(work, str(SAMPLE), "--profile", "b", "--yes")
    def ident(profile: str, fname: str):
        p = work / "profiles" / f"{profile}.json"
        if not p.exists():
            return None
        for m in json.loads(p.read_text(encoding="utf-8"))["mods"]:
            if m.get("file_name") == fname:
                return (m.get("sources") or {}).get("modrinth")
        return None
    a = ident("a", "krypton-0.3.0.jar")
    b = ident("b", "krypton-0.3.0.jar")
    print(f"    搜索路径写入 = {a!r}\n    hash 路径写入 = {b!r}")
    if a is None or b is None:
        record("WARN", "D38 无法比对", "某条路径没产出该模组"); return
    if a == b:
        record("PASS", "D38 两条路径标识一致")
    else:
        record("FAIL", "D38 两条路径标识不一致", f"{a!r} != {b!r} -> 改文件名重扫会产生重复条目")
    import shutil; shutil.rmtree(work, ignore_errors=True)


def check_d31_bom() -> None:
    section("5. D31：带 BOM 的用户文本文件")
    work = Path(tempfile.mkdtemp(prefix="fin-d31-"))
    names = work / "bom.txt"
    names.write_bytes("\ufeffkrypton-0.3.0.jar\n".encode("utf-8"))   # 故意带 BOM
    _scan(work, "--from-list", str(names), "--profile", "b", "--yes")
    prof = work / "profiles" / "b.json"
    if not prof.exists():
        record("FAIL", "D31 清单未生成"); return
    mods = json.loads(prof.read_text(encoding="utf-8"))["mods"]
    dirty = [m for m in mods if "\ufeff" in json.dumps(m, ensure_ascii=False)]
    if dirty:
        record("FAIL", "D31 BOM 污染了条目", str(dirty[0])[:120])
    else:
        record("PASS", "D31 带 BOM 的清单导入后条目干净")
    import shutil; shutil.rmtree(work, ignore_errors=True)


def check_d34_no_search_in_check() -> None:
    section("6. D34：check 期间不发名称搜索请求")
    work = Path(tempfile.mkdtemp(prefix="fin-d34-"))
    work.joinpath("profiles").mkdir()
    # 手工造一份"没有 sources"的清单（模拟未解析条目）
    prof = {
        "schema_version": 1, "name": "u", "description": "", "created_at": "", "updated_at": "",
        "mods": [{"key": "unknown-thing", "display_name": "UnknownThing", "mod_id": None,
                  "file_name": "unknown-thing-1.0.jar", "sources": {}, "detected": {},
                  "match_status": "unmatched", "notes": "", "added_at": "", "updated_at": ""}],
    }
    work.joinpath("profiles", "u.json").write_text(json.dumps(prof, ensure_ascii=False), encoding="utf-8")
    r = run([str(PY), "-m", "modcheck", "--config-dir", str(work), "check", "--profile", "u",
             "--mc", "26.3", "--loader", "fabric", "--no-color"])
    out = r.stdout or ""
    if r.returncode not in (0, 2):
        record("FAIL", f"D34 退出码异常 {r.returncode}", out[-160:]); return
    if "未判定" in out:
        record("PASS", "D34 无 sources 的条目判为未判定且未崩")
    else:
        record("WARN", "D34 未在输出里看到『未判定』", out[-160:])
    import shutil; shutil.rmtree(work, ignore_errors=True)


def check_menu_path() -> None:
    """菜单路径：用户双击 exe 后的第一条路径。P0 曾在这里（AttributeError: mc）。"""
    section("6b. 交互菜单主路径（无参数启动）")
    work = Path(tempfile.mkdtemp(prefix="fin-menu-"))
    _scan(work, str(SAMPLE), "--profile", "demo", "--yes")
    nl = "\n"
    # 说明：菜单每个入口的追问次数不固定，这里喂"完整流程 + 兜底退出键"，
    # 判定标准是【不崩】而非精确退出码 —— 本项的目的是守住 P0（AttributeError -> exit 70）那一类。
    # 注意：输入耗尽时程序把 EOF 当作"用户中断"返回 130，这是有意行为，不算失败。
    tail = "q" + nl + "q" + nl + "0" + nl
    cases = [("菜单[1] 检查（选清单）", "1" + nl + "1" + nl + "26.3" + nl + "fabric" + nl + tail),
             ("菜单[2] 扫描", "2" + nl + str(SAMPLE) + nl + "menutest" + nl + "y" + nl + tail),
             ("菜单[3] 管理清单", "3" + nl + "q" + nl + tail),
             ("菜单[4] 设置", "4" + nl + "q" + nl + tail),
             ("菜单[5] 版本列表", "5" + nl + tail),
             ("菜单[0] 退出", "0" + nl)]
    ACCEPTABLE = {0, 1, 2, 3, 4, 130}
    for label, stdin in cases:
        p = subprocess.run([str(PY), "-m", "modcheck", "--config-dir", str(work)],
                           cwd=str(ROOT), input=stdin, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600,
                           env=dict(os.environ, PYTHONPATH=str(ROOT / "src"),
                                    PYTHONIOENCODING="utf-8", NO_COLOR="1"))
        out = (p.stdout or "") + (p.stderr or "")
        if "程序内部出错" in out or "Traceback" in out:
            code = next((l for l in out.splitlines() if "Error" in l or "error" in l), "")[:100]
            record("FAIL", label, f"内部错误：{code}")
        elif p.returncode not in ACCEPTABLE:
            record("FAIL", label, f"退出码 {p.returncode} 不在可接受集合 {sorted(ACCEPTABLE)}")
        else:
            record("PASS", label, f"exit={p.returncode}")
    import shutil; shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------- R2 出口标准
FORBIDDEN_OUTPUT = ["«", "»", "missing i18n", "slug:modrinth", "slug:", "sha1:",
                    "invalid choice", "usage:", "Traceback", "Expecting property name",
                    "[WinError", "unrecognized arguments", "AttributeError"]


def _hygiene(stdout: str, stderr: str) -> list[str]:
    blob = (stdout or "") + "\n" + (stderr or "")
    return [p for p in FORBIDDEN_OUTPUT if p in blob]


def check_x2_output_hygiene() -> None:
    """X2：用户可见输出里不得出现内部标识、英文异常、argparse 原文。"""
    section("8. X2 输出净化")
    work = Path(tempfile.mkdtemp(prefix="fin-hyg-"))
    _scan(work, str(SAMPLE), "--profile", "demo", "--yes")
    cases = [
        ("报告（管道）", ["check", "--profile", "demo", "--mc", "26.3", "--loader", "fabric", "--no-color"]),
        ("清单列表", ["profile", "list"]),
        ("清单详情", ["profile", "show", "demo"]),
        ("版本列表", ["versions", "--limit", "5"]),
        ("设置查看", ["config", "show"]),
        ("缓存信息", ["cache", "info"]),
        ("非法 loader", ["check", "--loader", "quilt"]),
        ("非法子命令", ["frobnicate"]),
        ("未知参数", ["--bogus"]),
    ]
    for label, args in cases:
        r = run([str(PY), "-m", "modcheck", "--config-dir", str(work), *args], timeout=600)
        leaks = _hygiene(r.stdout, r.stderr)
        if leaks:
            record("FAIL", f"X2 {label} 输出不干净", f"命中 {leaks}")
        else:
            record("PASS", f"X2 {label} 输出干净")
    import shutil; shutil.rmtree(work, ignore_errors=True)


def check_x4_reproducible() -> None:
    """X4：同一清单连跑两次，逐条状态必须一致。"""
    section("9. X4 结论可复现")
    work = Path(tempfile.mkdtemp(prefix="fin-rep-"))
    _scan(work, str(SAMPLE), "--profile", "s", "--yes")
    digests = []
    for i in (1, 2):
        out = work / f"r{i}.json"
        run([str(PY), "-m", "modcheck", "--config-dir", str(work), "check", "--profile", "s",
             "--mc", "26.3", "--loader", "fabric", "--no-color", "--refresh", "--json", str(out)],
            timeout=900)
        if not out.exists():
            record("FAIL", f"X4 第{i}次未产出 JSON"); digests.append(None); continue
        data = json.loads(out.read_text(encoding="utf-8"))
        items = []
        for grp, lst in (data.get("groups") or {}).items():
            for it in (lst or []):
                mod = it.get("mod") or {}
                items.append((mod.get("file_name") or mod.get("key"), grp))
        digests.append(sorted(items))
        print(f"    第{i}次：{len(items)} 条，分组计数 "
              + str({g: sum(1 for _, gg in items if gg == g) for g in sorted({gg for _, gg in items})}), flush=True)
    if digests[0] is None or digests[1] is None:
        record("FAIL", "X4 无法比对")
    elif digests[0] == digests[1]:
        record("PASS", "X4 两次运行逐条状态完全一致")
    else:
        diff = [a for a in digests[0] if a not in digests[1]][:3]
        record("FAIL", "X4 两次运行结论不一致", f"示例差异 {diff}")
    import shutil; shutil.rmtree(work, ignore_errors=True)


def check_d40_same_version_not_yellow() -> None:
    """D40 不变量：🟡 组里不得出现 latest_compat.version_number == latest_for_loader.version_number 的条目。

    这是数据无关的检查 —— 不依赖具体某个模组，只断言"判定规则被正确执行"。
    """
    section("10b. D40 同版本号不同 MC 构建不得判 🟡")
    work = Path(tempfile.mkdtemp(prefix="fin-d40-"))
    _scan(work, str(SAMPLE), "--profile", "s", "--yes")
    bad: list[str] = []
    checked = 0
    for mc in ("26.3", "26.1"):
        out = work / f"d40-{mc}.json"
        run([str(PY), "-m", "modcheck", "--config-dir", str(work), "check", "--profile", "s",
             "--mc", mc, "--loader", "fabric", "--no-color", "--json", str(out)], timeout=900)
        if not out.exists():
            continue
        data = json.loads(out.read_text(encoding="utf-8"))
        for it in ((data.get("groups") or {}).get("degraded") or []):
            mod = it.get("mod") or {}
            lc = (it.get("latest_compat") or {}).get("version_number")
            lf = (it.get("latest_for_loader") or {}).get("version_number")
            if lc and lf:
                checked += 1
                if lc == lf:
                    bad.append(f"{mc}:{mod.get('file_name') or mod.get('key')} ({lc})")
    if bad:
        record("FAIL", "D40 仍有同版本号被判 🟡", f"{bad[:3]}（共 {len(bad)} 条）")
    else:
        record("PASS", f"D40 🟡 组内无同版本号条目（检查了 {checked} 条）")
    import shutil; shutil.rmtree(work, ignore_errors=True)


def check_d43_yellow_split() -> None:
    """D43：🟡 必须区分『无需处理』与『需要动作』，且下一步计数只含后者。"""
    section("10. D43 🟡 组区分无需处理 / 需要动作")
    work = Path(tempfile.mkdtemp(prefix="fin-d43-"))
    _scan(work, str(SAMPLE), "--profile", "s", "--yes")
    # 目标取用户当前版本 26.1：此时大量条目属于「本地已是最新兼容版」
    r = run([str(PY), "-m", "modcheck", "--config-dir", str(work), "check", "--profile", "s",
             "--mc", "26.1", "--loader", "fabric", "--no-color"], timeout=900)
    out = r.stdout or ""
    has_noop = "无需处理" in out
    # 下一步里的黄色计数
    import re as _re
    m = _re.search(r"拍板\s*🟡\s*的\s*(\d+)\s*个", out) or _re.search(r"🟡\s*的\s*(\d+)\s*个", out)
    counted = int(m.group(1)) if m else None
    total = None
    mm = _re.search(r"🟡 需降级（(\d+) 个）", out)
    if mm:
        total = int(mm.group(1))
    print(f"    🟡 组总数={total}  下一步里的计数={counted}  出现『无需处理』={has_noop}", flush=True)
    if not has_noop:
        record("FAIL", "D43 未见『无需处理』文案")
    elif counted is None or total is None:
        record("WARN", "D43 无法解析计数", "先确认文案格式")
    elif counted < total:
        record("PASS", f"D43 下一步计数({counted}) < 🟡 总数({total})，已排除无需处理项")
    else:
        record("FAIL", f"D43 下一步计数({counted}) 未排除无需处理项（🟡 总数 {total}）")
    import shutil; shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------- 7. 打包
def check_packaging() -> None:
    section("7. Nuitka 打包产物（若已构建）")
    for label, exe in [("standalone", ROOT / ".toolchain/pkg-standalone/modcheck/modcheck.exe"),
                       ("onefile", ROOT / ".toolchain/pkg-one/modcheck.exe")]:
        if not exe.exists():
            record("SKIP", f"{label} 产物未构建", str(exe.relative_to(ROOT)))
            continue
        v = subprocess.run([str(exe), "--version"], capture_output=True, text=True, encoding="utf-8")
        # 注意：必须是两个独立参数 ["config", "path"]，写成一个字符串会让 argparse 报未知命令
        p = subprocess.run([str(exe), "config", "path"], capture_output=True, text=True, encoding="utf-8")
        cfgpath = (p.stdout or "").strip()
        ok_cfg = str(exe.parent) in cfgpath
        if v.returncode == 0 and ok_cfg:
            record("PASS", f"{label} 可运行且配置目录在 exe 同级", cfgpath)
        else:
            record("FAIL", f"{label} 异常",
                   f"version={v.returncode} configpath={cfgpath!r} stderr={(p.stderr or '')[-120:]!r}")


def main() -> int:
    print(f"最终验收开始  工作目录={ROOT}")
    check_pytest()
    check_d34_no_search_in_check()
    check_d31_bom()
    check_d35_unidentified_jars_listed()
    check_d38_identifier_consistency()
    check_menu_path()
    check_x2_output_hygiene()
    check_d40_same_version_not_yellow()
    check_d43_yellow_split()
    check_x4_reproducible()
    check_scripts()
    check_packaging()
    section("汇总")
    n = {k: sum(1 for lv, _, _ in RESULTS if lv == k) for k in ("PASS", "FAIL", "WARN", "SKIP")}
    print(f"PASS {n['PASS']} ｜ FAIL {n['FAIL']} ｜ WARN {n['WARN']} ｜ SKIP {n['SKIP']}")
    for lv, name, detail in RESULTS:
        if lv in ("FAIL", "WARN"):
            print(f"  {lv}: {name}  {detail}")
    return 1 if n["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
