# -*- coding: utf-8 -*-
"""主 Agent 独立验证 classify()：分支矩阵 + 陷阱场景 + 文案 key 完整性。"""
import sys
from pathlib import Path

ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))

from modcheck.core.checker import REASON_KEYS, classify, for_reason
from modcheck.core.models import Loader, ReasonCode, Status, VersionInfo
from modcheck.i18n import t

results = []


def V(vid, num, *, type_="release", gv=("26.3",), loaders=("fabric",)):
    return VersionInfo(version_id=vid, version_number=num, name=num, project_id="P",
                       date_published="2026-09-18T00:00:00Z", version_type=type_,
                       game_versions=tuple(gv), loaders=tuple(loaders), files=())


def chk(label, got, want, note=""):
    ok = got == want
    results.append(ok)
    print(f"  {'OK  ' if ok else 'FAIL'} {label:58s} got={got!r}" + ("" if ok else f"  want={want!r}")
          + (f"  {note}" if note else ""))


def chk_cls(label, c, want_status, want_reason, note=""):
    ok = (c.status == want_status and c.reason == want_reason)
    results.append(ok)
    print(f"  {'OK  ' if ok else 'FAIL'} {label:58s} {c.status.value}/{c.reason.value}"
          + ("" if ok else f"   want {want_status.value}/{want_reason.value}") + (f"  {note}" if note else ""))


F = Loader.FABRIC
print("=" * 100); print("【分支矩阵】"); print("=" * 100)

chk_cls("① 项目 0 个版本 → NO_FILES", classify(loader=F, mc_version="26.3", version_count=0),
        Status.BLOCKED, ReasonCode.NO_FILES)
chk_cls("① 无 fabric 文件 → NO_LOADER",
        classify(loader=F, mc_version="26.3", version_count=57, available_loaders=("forge", "neoforge")),
        Status.BLOCKED, ReasonCode.NO_LOADER)
v = V("1", "26.3")
chk_cls("③ 最新正式版就支持 → READY/OK",
        classify(loader=F, mc_version="26.3", releases_for_loader=[v], compat_releases=[v]),
        Status.READY, ReasonCode.OK)
a = [V("2", "26.3"), V("1", "26.1", gv=("26.1",))]; b = [V("1", "26.1", gv=("26.1",))]
chk_cls("④ 最新版不支持但有旧版 → OLD_VERSION_ONLY",
        classify(loader=F, mc_version="26.1", releases_for_loader=a, compat_releases=b),
        Status.DEGRADED, ReasonCode.OLD_VERSION_ONLY)
beta = [V("3", "31.8.0.49", type_="beta")]
chk_cls("⑤ 仅 beta 支持（调用方一致的输入）→ PRERELEASE_ONLY",
        classify(loader=F, mc_version="26.3", releases_for_loader=[], any_for_loader=beta,
                 compat_releases=[], compat_any=beta),
        Status.DEGRADED, ReasonCode.PRERELEASE_ONLY)
alpha = [V("4", "0.9.3-alpha.1", type_="alpha")]
chk_cls("② + ⑤ 该加载器只有 alpha → PRERELEASE_ONLY",
        classify(loader=F, mc_version="26.3", releases_for_loader=[], any_for_loader=alpha,
                 compat_releases=[], compat_any=alpha),
        Status.DEGRADED, ReasonCode.PRERELEASE_ONLY)
c = classify(loader=F, mc_version="26.3", releases_for_loader=[V("5", "26.2", gv=("26.2",)), V("6", "26.1", gv=("26.1",))],
             compat_releases=[])
chk_cls("⑥ 有文件但都不支持 → NO_MC_VERSION", c, Status.BLOCKED, ReasonCode.NO_MC_VERSION)
chk("⑥ max_supported_mc = 26.2", c.max_supported_mc, "26.2")
c = classify(loader=F, mc_version="26.3", releases_for_loader=[V("7", "x", gv=("26.2", "26.4-snapshot-2"))], compat_releases=[])
chk("⑥ 快照不得算作 max_supported_mc", c.max_supported_mc, "26.2")

print(); print("=" * 100); print("【真实数据陷阱】"); print("=" * 100)
jm = V("fa", "26.3-6.0.9+fabric")
chk_cls("JourneyMap 多加载器同版本号 → 必须 READY",
        classify(loader=F, mc_version="26.3", releases_for_loader=[jm], compat_releases=[jm]),
        Status.READY, ReasonCode.OK)
c = classify(loader=F, mc_version="26.1",
             releases_for_loader=[V("old", "19.51.0.418", gv=("1.21.1",)), V("new", "29.34.0.90", gv=("26.1",))],
             compat_releases=[V("new", "29.34.0.90", gv=("26.1",))])
chk_cls("作者重发旧版本 → OLD_VERSION_ONLY（不误判 READY）", c, Status.DEGRADED, ReasonCode.OLD_VERSION_ONLY)
chk("  且 latest_for_loader 保留 A[0]", c.latest_for_loader.version_number, "19.51.0.418")

pb = V("p", "3.6.0-beta.2", type_="beta")
chk_cls("--pre 下最新版支持 → READY（不产生 PRERELEASE_ONLY）",
        classify(loader=F, mc_version="26.3", releases_for_loader=[pb], compat_releases=[pb], prerelease=True),
        Status.READY, ReasonCode.OK)
chk_cls("--pre 下仅有 beta 但不支持 → NO_MC_VERSION",
        classify(loader=F, mc_version="26.3", releases_for_loader=[V("q", "9.9", type_="beta", gv=("26.2",))],
                 compat_releases=[V("q", "9.9", type_="beta", gv=("26.2",))], prerelease=True),
        Status.BLOCKED, ReasonCode.NO_MC_VERSION)

print(); print("=" * 100); print("【非版本判定】"); print("=" * 100)
for reason, want in [(ReasonCode.NOT_FOUND, Status.BLOCKED), (ReasonCode.NO_FILES, Status.BLOCKED),
                     (ReasonCode.ERROR, Status.UNKNOWN), (ReasonCode.UNMATCHED, Status.UNKNOWN),
                     (ReasonCode.IGNORED, Status.IGNORED)]:
    chk_cls(f"for_reason({reason.value})", for_reason(reason), want, reason)

print(); print("=" * 100); print("【文案 key 完整性】"); print("=" * 100)
bad = []
for rc in ReasonCode:
    keys = REASON_KEYS.get(rc)
    if not keys:
        bad.append(f"{rc.value}: 缺 REASON_KEYS"); continue
    for k in keys:
        try:
            t(k)
        except Exception as e:
            bad.append(f"{rc.value}->{k}: {type(e).__name__}")
print("  " + ("✅ 全部 reason_code 都有可解析文案 key" if not bad else "❌ " + "; ".join(bad)))
results.append(not bad)

print(); print("=" * 100)
n = sum(results)
print(f"合计 {n}/{len(results)} 通过" + ("   ✅ 全部通过" if n == len(results) else "   ❌ 有失败"))
raise SystemExit(0 if n == len(results) else 1)
