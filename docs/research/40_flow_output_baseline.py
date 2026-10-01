# -*- coding: utf-8 -*-
"""流程层输出基线：scan / check 两条 CLI 流水线的**进程内**逐字节回归工具。

为什么需要它：docs/research/golden 的 13 个用例只覆盖 --help/--version/profile/config/cache
与参数错误，**没有一条真正跑 scan 或 check 的流水线**。流程下沉重构（0 期）动的正是这两条，
所以另外抓一份它们的完整输出（含进度行、清单落盘结果、导出文件内容）。

用法（重构前后各抓一次，再逐字节对比）：

    $py = .toolchain\Python311\python.exe
    $env:PYTHONPATH='src;tests'

    # ① 重构前：CAPTURE_SRC 指向重构前的代码（git worktree / 上一版）
    git worktree add --detach .toolchain\tmp\pre HEAD
    $env:CAPTURE_SRC="$pwd\.toolchain\tmp\pre\src"
    & $py docs\research\40_flow_output_baseline.py capture .toolchain\tmp\before.json

    # ② 重构后
    $env:CAPTURE_SRC="$pwd\src"
    & $py docs\research\40_flow_output_baseline.py capture .toolchain\tmp\after.json

    # ③ 对比（有任何一处不同都会打印出来并以 1 退出）
    & $py docs\research\40_flow_output_baseline.py compare .toolchain\tmp\before.json .toolchain\tmp\after.json

注意：报告头里的"检查时间/用时"天然不可复现，脚本已统一归一化成 <TIME>/<ELAPSED>；
mods 文件夹只生成一次（zipfile 会把当前时间写进 jar，重生成会让 sha1 变）。

⚠️ 一条**预期内**的差异（R4 复核裁决 5）：交互匹配里选 q 的语义修复
（core.checker_run.check_one 不再吞 UserCancelled）会让 check_interactive_quit 场景
从 exit=2（该模组变 ⚪ + 「程序内部出错」）变成 exit=130（已中断）—— 这是规格要求的修正，
不是回归；除它之外的 29 个场景必须与修复前逐字节一致。
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import time
from argparse import Namespace
from pathlib import Path

ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
#: 被测源码目录：默认本工作区；指向 git worktree 就能跑"重构前"的代码
SRC = Path(os.environ.get("CAPTURE_SRC") or (ROOT / "src"))
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT / "tests"))

# 冻结生成时间（只影响展示，不碰 monotonic —— 限速器要靠真实时钟推进）
time.strftime = lambda fmt="", *a: "<TIME>"          # type: ignore[assignment]

#: 报告/导出里的时间与耗时是唯一"天然不可复现"的字段，统一归一化后再比较
_TIME_LINE = re.compile(r"(检查时间：)\S+(\s+｜\s+用时 )\d+( 秒)")
_JSON_TIME = re.compile(r'("generated_at":\s*)"[^"]*"')
_JSON_ELAPSED = re.compile(r'("elapsed":\s*)[0-9.]+')


def normalize(text: str) -> str:
    text = _TIME_LINE.sub(r"\1<TIME>\2<ELAPSED>\3", text)
    text = _JSON_TIME.sub(r'\1"<TIME>"', text)
    return _JSON_ELAPSED.sub(r"\1<ELAPSED>", text)

from fakes import FakeProvider, FakeTransport, json_response  # noqa: E402
from make_fixtures import make_mods_dir  # noqa: E402

from modcheck.cli.commands.check import run_check  # noqa: E402
from modcheck.cli.commands.scan import run_scan  # noqa: E402
from modcheck.cli.context import AppContext  # noqa: E402
from modcheck.cli.prompts import Prompter  # noqa: E402
from modcheck.console import Console  # noqa: E402
from modcheck.core.models import (Loader, MatchStatus, ModEntry, ProjectHit,  # noqa: E402
                                  ProjectInfo, Settings, SourceKind, VersionInfo)
from modcheck.errors import ProviderNetworkError, ProviderUnavailable  # noqa: E402
from modcheck.providers.http import HttpConfig, HttpClient  # noqa: E402
from modcheck.providers.modrinth import ModrinthProvider  # noqa: E402
from modcheck.providers.registry import ProviderRegistry  # noqa: E402
from modcheck.storage.profiles import new_profile, profile_path, save_profile  # noqa: E402

TMP = ROOT / ".toolchain" / "tmp" / "flow_baseline" / "work"
RUN = [0]


def fresh_dir(tag: str) -> Path:
    import shutil

    RUN[0] += 1
    path = TMP / (tag + "-" + str(RUN[0]))
    if path.exists():          # 上一次运行的残留必须清掉，否则第二次跑就不是"全新"场景
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


#: mods 文件夹只生成一次并复用：zipfile 会把当前时间写进 jar，每次重生成 sha1 都会变
SHARED_MODS = ROOT / ".toolchain" / "tmp" / "flow_baseline" / "shared_mods"


def shared_mods() -> Path:
    target = SHARED_MODS / "mods"
    if not target.exists():
        make_mods_dir(target)
    return target


def V(pid: str, number: str, mc: tuple[str, ...], vtype: str = "release") -> VersionInfo:
    return VersionInfo.from_api({"id": pid + number, "project_id": pid, "version_number": number,
                                 "name": number, "date_published": "2026-09-18T00:00:00Z",
                                 "version_type": vtype, "game_versions": list(mc),
                                 "loaders": ["fabric"], "files": []})


def PI(pid: str, loaders: tuple[str, ...] = ("forge",), count: int = 3) -> ProjectInfo:
    return ProjectInfo(project_id=pid, slug=pid, title=pid.title(), description="",
                       project_type="mod", loaders=loaders, game_versions=(),
                       downloads=0, version_count=count)


def entry(key: str, **kw: object) -> ModEntry:
    return ModEntry(key=key, display_name=str(kw.pop("display", key)), mod_id=key,
                    sources={"modrinth": key}, source_kind=SourceKind.HASH, **kw)  # type: ignore[arg-type]


def make_ctx(cfg: Path, provider, *, offline: bool = True, interactive: bool = False,
             prompter=None, debug: bool = False, settings: Settings | None = None,
             transport=None, registry=None, client: HttpClient | None = None) -> AppContext:
    if transport is None:
        def handler(method: str, url: str, data, index: int):
            raise ProviderNetworkError("offline")
        transport = FakeTransport(handler)
    if client is None:
        client = HttpClient(HttpConfig(rate_limit_per_min=100000, retries=0),
                            transport=transport)
    console = Console(stream=io.StringIO(), color="never", width=100)
    if registry is None:
        registry = ProviderRegistry(providers=[provider] if provider is not None else [])
    return AppContext(settings=settings or Settings(), config_dir=cfg, console=console,
                      registry=registry, cache=None, client=client,
                      prompter=prompter, interactive=interactive, debug=debug)


def out_of(ctx: AppContext) -> str:
    return ctx.console.stream.getvalue()  # type: ignore[attr-defined]


def write_profile(cfg: Path, entries: list[ModEntry], name: str = "demo") -> Path:
    (cfg / "profiles").mkdir(parents=True, exist_ok=True)
    profile = new_profile(name)
    profile.mods = entries
    path = profile_path(cfg / "profiles", name)
    save_profile(profile, path)
    return path


def check_args(**over: object) -> Namespace:
    base: dict[str, object] = dict(
        profile=None, file=None, mods_dir=None, mc="26.3", loader="fabric",
        json_out=None, md_out=None, csv_out=None, refresh=False, jobs=None,
        yes=True, pre=False, quiet=False, window=25, debug=False, no_color=True,
        resolve=False)
    base.update(over)
    return Namespace(**base)


def scan_args(**over: object) -> Namespace:
    base: dict[str, object] = dict(paths=[], from_list=None, profile="demo", new=True, yes=True)
    base.update(over)
    return Namespace(**base)


def scan_provider() -> FakeProvider:
    hits = [ProjectHit("Pcarpet", "carpet", "Carpet", 11016662, "d", "fake"),
            ProjectHit("Papi", "fabric-api", "Fabric API", 5000000, "d", "fake"),
            ProjectHit("Pli", "lithium", "Lithium", 3000000, "d", "fake")]
    version = VersionInfo.from_api({
        "id": "V1", "project_id": "Papi", "version_number": "0.92.2+1.20.1",
        "name": "0.92.2+1.20.1", "date_published": "2026-01-01T00:00:00Z",
        "version_type": "release", "game_versions": ["1.20.1"], "loaders": ["fabric"],
        "files": []})
    return FakeProvider(hits=hits, hash_map={"deadbeef": version})


CASES: list[tuple[str, object]] = []


def case(name: str):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


# ---------------------------------------------------------------- scan
@case("scan_dir_new")
def _scan_dir_new():
    cfg = fresh_dir("scan-new")
    mods = shared_mods()
    ctx = make_ctx(cfg, scan_provider())
    code = run_scan(scan_args(paths=[str(mods)], new=True), ctx)
    return code, out_of(ctx)


@case("scan_dir_merge")
def _scan_dir_merge():
    cfg = fresh_dir("scan-merge")
    mods = shared_mods()
    ctx = make_ctx(cfg, scan_provider())
    first = run_scan(scan_args(paths=[str(mods)], new=True), ctx)
    second = run_scan(scan_args(paths=[str(mods)], new=False), ctx)
    return [first, second], out_of(ctx)


@case("scan_from_list")
def _scan_from_list():
    cfg = fresh_dir("scan-list")
    listing = cfg / "list.txt"
    listing.write_text("[\u5730\u6bef] fabric-carpet-26.1+v260402.jar\n"
                       "lithium-fabric-0.12.1.jar\n# \u6ce8\u91ca\n", encoding="utf-8")
    ctx = make_ctx(cfg, scan_provider())
    code = run_scan(scan_args(from_list=str(listing)), ctx)
    return code, out_of(ctx)


@case("scan_offline")
def _scan_offline():
    cfg = fresh_dir("scan-offline")
    mods = shared_mods()
    ctx = make_ctx(cfg, FakeProvider(raise_on={"*": ProviderUnavailable("offline")}))
    code = run_scan(scan_args(paths=[str(mods)]), ctx)
    return code, out_of(ctx)


@case("scan_no_dir")
def _scan_no_dir():
    cfg = fresh_dir("scan-nodir")
    ctx = make_ctx(cfg, scan_provider())
    return run_scan(scan_args(), ctx), out_of(ctx)


@case("scan_missing_dir")
def _scan_missing_dir():
    cfg = fresh_dir("scan-missing")
    ctx = make_ctx(cfg, scan_provider())
    return run_scan(scan_args(paths=[str(cfg / "nope")]), ctx), out_of(ctx)


# ---------------------------------------------------------------- check
@case("check_ready")
def _check_ready():
    cfg = fresh_dir("check-ready")
    provider = FakeProvider(releases={"ok": [V("ok", "26.3", ("26.3",))]})
    path = write_profile(cfg, [entry("ok", display="Ok")])
    ctx = make_ctx(cfg, provider)
    return run_check(check_args(file=str(path)), ctx), out_of(ctx)


@case("check_mixed_groups")
def _check_mixed_groups():
    cfg = fresh_dir("check-mixed")
    newest = V("n", "26.3", ("26.3",))
    compat = V("c", "26.1", ("26.1",))
    beta = V("b", "26.3-beta", ("26.3",), "beta")
    provider = FakeProvider(releases={"bad": [], "old": [newest], "pre": []},
                            compat={"old": [compat]},
                            compat_all={"pre": [beta]},
                            any_loader={"bad": [], "pre": [beta]},
                            projects={"bad": PI("bad")})
    entries = [entry("ok", display="Ok"), entry("bad", display="Bad"),
               entry("old", display="Old"), entry("pre", display="Pre"),
               ModEntry(key="mystery", display_name="Mystery"),
               ModEntry(key="ig", display_name="Ignored", match_status=MatchStatus.IGNORED)]
    path = write_profile(cfg, entries)
    ctx = make_ctx(cfg, provider)
    return run_check(check_args(file=str(path)), ctx), out_of(ctx)


@case("check_quiet")
def _check_quiet():
    cfg = fresh_dir("check-quiet")
    provider = FakeProvider(releases={"ok": [V("ok", "26.3", ("26.3",))]})
    path = write_profile(cfg, [entry("ok", display="Ok")])
    ctx = make_ctx(cfg, provider)
    return run_check(check_args(file=str(path), quiet=True), ctx), out_of(ctx)


@case("check_many_progress")
def _check_many_progress():
    cfg = fresh_dir("check-many")
    provider = FakeProvider(releases={("m%d" % i): [V("m%d" % i, "26.3", ("26.3",))]
                                      for i in range(7)})
    entries = [entry("m%d" % i, display="Mod %d" % i) for i in range(7)]
    path = write_profile(cfg, entries)
    ctx = make_ctx(cfg, provider)
    return run_check(check_args(file=str(path)), ctx), out_of(ctx)


@case("check_network_error")
def _check_network_error():
    cfg = fresh_dir("check-neterr")
    provider = FakeProvider(raise_on={"*": ProviderNetworkError("timeout")})
    path = write_profile(cfg, [entry("x", display="X")])
    ctx = make_ctx(cfg, provider)
    return run_check(check_args(file=str(path)), ctx), out_of(ctx)


@case("check_degraded")
def _check_degraded():
    cfg = fresh_dir("check-degraded")
    provider = FakeProvider(releases={"old": [V("n", "26.3", ("26.3",))]},
                            compat={"old": [V("c", "26.1", ("26.1",))]})
    path = write_profile(cfg, [entry("old", display="Old")])
    ctx = make_ctx(cfg, provider)
    return run_check(check_args(file=str(path), mc="26.1"), ctx), out_of(ctx)


@case("check_unmatched")
def _check_unmatched():
    cfg = fresh_dir("check-unmatched")
    provider = FakeProvider(hits=[ProjectHit("P9", "other-mod", "Other Mod", 1, "d", "fake")])
    path = write_profile(cfg, [ModEntry(key="mystery", display_name="Mystery")])
    ctx = make_ctx(cfg, provider)
    return run_check(check_args(file=str(path)), ctx), out_of(ctx)


@case("check_resolve")
def _check_resolve():
    cfg = fresh_dir("check-resolve")
    provider = FakeProvider(hits=[ProjectHit("P9", "mystery", "Mystery", 1, "d", "fake")],
                            releases={"mystery": [V("mystery", "26.3", ("26.3",))]})
    path = write_profile(cfg, [ModEntry(key="mystery", display_name="Mystery",
                                        mod_id="mystery")])
    ctx = make_ctx(cfg, provider)
    return run_check(check_args(file=str(path), resolve=True), ctx), out_of(ctx)


@case("check_no_provider")
def _check_no_provider():
    cfg = fresh_dir("check-nosrc")
    path = write_profile(cfg, [entry("a")])
    ctx = make_ctx(cfg, None)
    return run_check(check_args(file=str(path)), ctx), out_of(ctx)


@case("check_interrupt")
def _check_interrupt():
    cfg = fresh_dir("check-int")
    provider = FakeProvider(raise_on={"releases_for_loader": KeyboardInterrupt()})
    path = write_profile(cfg, [entry("m%d" % i, display="M%d" % i) for i in range(30)])
    ctx = make_ctx(cfg, provider)
    return run_check(check_args(file=str(path), jobs=1), ctx), out_of(ctx)


@case("check_export")
def _check_export():
    cfg = fresh_dir("check-export")
    provider = FakeProvider(releases={"ok": [V("ok", "26.3", ("26.3",))]})
    path = write_profile(cfg, [entry("ok", display="Ok")])
    ctx = make_ctx(cfg, provider)
    target = cfg / "out"
    target.mkdir()
    code = run_check(check_args(file=str(path), json_out=str(target / "r.json"),
                                md_out=str(target / "r.md"), csv_out=str(target / "r.csv")), ctx)
    files = {p.name: p.read_text(encoding="utf-8")
             for p in sorted(target.iterdir()) if p.is_file()}
    return code, out_of(ctx) + "\n===EXPORTS===\n" + json.dumps(files, ensure_ascii=False,
                                                                indent=1, sort_keys=True)


@case("check_mods_dir")
def _check_mods_dir():
    cfg = fresh_dir("check-modsdir")
    mods = shared_mods()
    ctx = make_ctx(cfg, scan_provider())
    return run_check(check_args(mods_dir=str(mods)), ctx), out_of(ctx)


@case("check_mods_dir_and_profile")
def _check_mods_dir_and_profile():
    cfg = fresh_dir("check-mutex")
    ctx = make_ctx(cfg, scan_provider())
    return run_check(check_args(profile="demo", mods_dir=str(cfg)), ctx), out_of(ctx)


@case("check_mods_dir_no_provider")
def _check_mods_dir_no_provider():
    cfg = fresh_dir("check-modsdir-nosrc")
    mods = shared_mods()
    ctx = make_ctx(cfg, None)
    return run_check(check_args(mods_dir=str(mods)), ctx), out_of(ctx)


@case("scan_two_dirs")
def _scan_two_dirs():
    cfg = fresh_dir("scan-two")
    first = shared_mods()
    second = fresh_dir("mods-extra") / "mods"
    make_mods_dir(second)
    ctx = make_ctx(cfg, scan_provider())
    code = run_scan(scan_args(paths=[str(first), str(second)]), ctx)
    return code, out_of(ctx)


@case("check_missing_profile")
def _check_missing_profile():
    cfg = fresh_dir("check-noprofile")
    ctx = make_ctx(cfg, scan_provider())
    return run_check(check_args(profile="nope"), ctx), out_of(ctx)


@case("check_no_profile_selected")
def _check_no_profile_selected():
    cfg = fresh_dir("check-nosel")
    ctx = make_ctx(cfg, scan_provider())
    return run_check(check_args(), ctx), out_of(ctx)


@case("check_bad_mc")
def _check_bad_mc():
    cfg = fresh_dir("check-badmc")
    path = write_profile(cfg, [entry("a")])
    ctx = make_ctx(cfg, scan_provider())
    return run_check(check_args(file=str(path), mc="not-a-version"), ctx), out_of(ctx)


@case("check_window_debug")
def _check_window_debug():
    cfg = fresh_dir("check-window")
    provider = FakeProvider(releases={"ok": [V("ok", "26.3", ("26.3",))]})
    path = write_profile(cfg, [entry("ok", display="Ok")])
    ctx = make_ctx(cfg, provider, debug=True)
    return run_check(check_args(file=str(path), window=3), ctx), out_of(ctx)


@case("check_interactive_pick")
def _check_interactive_pick():
    cfg = fresh_dir("check-interactive")
    provider = FakeProvider(hits=[ProjectHit("P9", "mystery", "Mystery", 1, "d", "fake")],
                            releases={"mystery": [V("mystery", "26.3", ("26.3",))]})
    path = write_profile(cfg, [ModEntry(key="mystery", display_name="Mystery",
                                        mod_id="mystery")])
    answers = iter(["1"])
    console = Console(stream=io.StringIO(), color="never", width=100)
    prompter = Prompter(input_fn=lambda prompt: next(answers), out=console)
    ctx = make_ctx(cfg, provider, interactive=True, prompter=prompter)
    ctx.console = console  # type: ignore[assignment]
    code = run_check(check_args(file=str(path)), ctx)
    saved = json.loads(Path(path).read_text(encoding="utf-8"))
    return code, out_of(ctx) + "\n===PROFILE===\n" + json.dumps(
        [m.get("sources") for m in saved["mods"]], ensure_ascii=False, sort_keys=True)


@case("check_interactive_quit")
def _check_interactive_quit():
    cfg = fresh_dir("check-interactive-q")
    provider = FakeProvider(hits=[ProjectHit("P9", "mystery", "Mystery", 1, "d", "fake")])
    path = write_profile(cfg, [ModEntry(key="mystery", display_name="Mystery",
                                        mod_id="mystery")])
    answers = iter(["q"])
    console = Console(stream=io.StringIO(), color="never", width=100)
    prompter = Prompter(input_fn=lambda prompt: next(answers), out=console)
    ctx = make_ctx(cfg, provider, interactive=True, prompter=prompter)
    ctx.console = console  # type: ignore[assignment]
    return run_check(check_args(file=str(path)), ctx), out_of(ctx)


@case("check_partial_failure")
def _check_partial_failure():
    cfg = fresh_dir("check-partial")

    def handler(method: str, url: str, data, index: int):
        if "version_manifest" in url:
            raise ProviderNetworkError("offline")
        return json_response([{"id": "V1", "project_id": "carpet", "version_number": "26.3",
                               "name": "26.3", "date_published": "2026-09-18T00:00:00Z",
                               "version_type": "release", "game_versions": ["26.3"],
                               "loaders": ["fabric"], "files": []}])

    transport = FakeTransport(handler)
    client = HttpClient(HttpConfig(rate_limit_per_min=100000, retries=0), transport=transport)
    ctx = make_ctx(cfg, None, client=client,
                   registry=ProviderRegistry(providers=[ModrinthProvider(client)]))
    path = write_profile(cfg, [entry("carpet", display="Carpet")])
    return run_check(check_args(file=str(path)), ctx), out_of(ctx)


@case("check_source_unavailable")
def _check_source_unavailable():
    cfg = fresh_dir("check-e01")

    def handler(method: str, url: str, data, index: int):
        raise ProviderNetworkError("connection refused")

    transport = FakeTransport(handler)
    client = HttpClient(HttpConfig(rate_limit_per_min=100000, retries=0), transport=transport)
    ctx = make_ctx(cfg, None, client=client,
                   registry=ProviderRegistry(providers=[ModrinthProvider(client)]))
    path = write_profile(cfg, [entry("carpet", display="Carpet")])
    return run_check(check_args(file=str(path)), ctx), out_of(ctx)


@case("check_rate_limited")
def _check_rate_limited():
    cfg = fresh_dir("check-429")

    def handler(method: str, url: str, data, index: int):
        if "version_manifest" in url:
            raise ProviderNetworkError("offline")
        return json_response({"error": "rate limited"}, status=429)

    transport = FakeTransport(handler)
    client = HttpClient(HttpConfig(rate_limit_per_min=100000, retries=0), transport=transport)
    ctx = make_ctx(cfg, None, client=client,
                   registry=ProviderRegistry(providers=[ModrinthProvider(client)]))
    path = write_profile(cfg, [entry("carpet", display="Carpet")])
    return run_check(check_args(file=str(path)), ctx), out_of(ctx)


def cmd_capture(target: Path) -> int:
    """跑完全部场景并把结果写成 JSON。"""
    results: dict[str, object] = {}
    for name, fn in CASES:
        try:
            code, text = fn()  # type: ignore[operator]
            results[name] = {"code": code, "out": normalize(text)}
        except BaseException as exc:  # noqa: BLE001  （错误路径也是基线的一部分）
            results[name] = {"exc": type(exc).__name__,
                             "message": getattr(exc, "message", str(exc)),
                             "hint": getattr(exc, "hint", ""),
                             "exit_code": getattr(exc, "exit_code", None)}
        print("  %-28s %s" % (name, json.dumps(results[name], ensure_ascii=False)[:110]))
    target.write_text(json.dumps(results, ensure_ascii=False, indent=1, sort_keys=True),
                      encoding="utf-8", newline="\n")
    print("\nwrote", target, "cases:", len(results))
    return 0


def cmd_compare(before: Path, after: Path) -> int:
    """逐字节（结构级）对比两份快照；有差异打印 diff 并以 1 退出。"""
    import difflib

    a = json.loads(before.read_text(encoding="utf-8"))
    b = json.loads(after.read_text(encoding="utf-8"))
    names = sorted(set(a) | set(b))
    bad = 0
    for name in names:
        if name not in a or name not in b or a[name] != b[name]:
            bad += 1
            print("=== DIFF", name)
            ta = json.dumps(a.get(name), ensure_ascii=False, indent=1).splitlines()
            tb = json.dumps(b.get(name), ensure_ascii=False, indent=1).splitlines()
            for line in list(difflib.unified_diff(ta, tb, "before", "after", lineterm=""))[:60]:
                print(line)
    print("cases:", len(names), " differ:", bad)
    return 1 if bad else 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="流程层输出基线：抓取 / 对比")
    sub = parser.add_subparsers(dest="command", required=True)
    cap = sub.add_parser("capture", help="跑完全部场景并写出 JSON")
    cap.add_argument("target", type=Path)
    cmp_ = sub.add_parser("compare", help="对比两份 JSON 快照")
    cmp_.add_argument("before", type=Path)
    cmp_.add_argument("after", type=Path)
    args = parser.parse_args()
    if args.command == "capture":
        return cmd_capture(args.target)
    return cmd_compare(args.before, args.after)


if __name__ == "__main__":
    raise SystemExit(main())
