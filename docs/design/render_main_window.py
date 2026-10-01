# -*- coding: utf-8 -*-
"""把正式的主窗口渲染成 PNG（不 show 窗口，grab 即可）。"""
import os, sys
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))
os.environ["QT_QPA_PLATFORM"] = "windows"

from PyQt6.QtWidgets import QApplication
from modcheck.gui.main_window import MainWindow, Row

BLOCKED = [("Antideath-Carpet-Add…", "v1.4.7-mc26.1 → v1.5.1-hotfix-mc26.1…", "2026-08-10",
            "最高只支持 MC 26.2，没有任何支持 26.3 的版本"),
           ("Carpet Extra", "26.1 → 26.2", "2026-06-21",
            "最高只支持 MC 26.2，没有任何支持 26.3 的版本")]
PRERELEASE = [("ScalableLux", "0.2.0+fabric.2b63825 → 0.2.1+fabr…", "2026-06-12", "0.3.0-alpha.0.6+26.3（alpha 通道）"),
              ("Server Replay", "3.4.3+26.1 → 3.5.2+26.2", "2026-08-09", "3.6.0-beta.2+26.3（beta 通道）"),
              ("gugle-carpet-addition-wra…", "v2.12.1+build.83（已是最新正式版）", "2026-04-25", "v2.12.8+build.97（beta 通道）"),
              ("TweakerMore", "v3.31.0-mc26.1.2 → v3.33.2-mc26.1…", "2026-08-30", "v3.33.3-beta.1-mc26.3（beta 通道）")]
DEGRADED = [("MagicLib", "v0.8.838-mc26.1.2-fabric → v0.8.8…", "2026-09-27", "v0.8.882-mc26.3-fabric（2026-09-27）"),
            ("Carpet AMS Addition", "mc26.1.2-v26.2 → mc1.18.2-v26.3", "2026-09-24", "mc26.3-v26.3（2026-09-24）"),
            ("Carpet Org Addition", "1.45.1 → 1.41.7 (v1.41.7+2609…)", "2026-09-27", "1.46.0（2026-09-16）")]
READY = ["ImmediatelyFast|1.15.2+26.1.2-fabric → 1.17.1+26.3|2026-09-17",
         "Carpet Extra Extras|26.1-1.4.0 → 26.3-1.4.2|2026-09-21",
         "Carpet TIS Addition|v1.81.0-mc26.1.2 → v1.82.4-mc26.3|2026-09-16",
         "EntityCulling|1.10.5 → 1.11.2|2026-09-21",
         "Fabric API|0.153.0+26.1.2 → 0.161.0+26.3|2026-09-18",
         "Carpet Mod|26.1 → 26.3 (v260915)|2026-09-18",
         "Fabric Language Kotlin|1.13.12+kotlin.2.4.0 → 1.14.1+kot…|2026-09-07",
         "FerriteCore|9.0.0-fabric（已是最新）|2026-03-24",
         "Krypton|0.3.0 → 0.3.2|2026-09-30",
         "Litematica|0.27.7 → 0.29.1|2026-09-27",
         "Litematica Server Paster|v1.3.13-mc26.1.2 → v1.3.14-mc26.3|2026-09-26",
         "Lithium|mc26.1.2-0.24.6-fabric → mc26.3-0…|2026-09-28",
         "MaLiLib|0.28.7 → 0.30.2|2026-09-27",
         "MidnightLib|1.9.3+26.1-fabric → 1.9.3+26.3-fa…|2026-09-13",
         "MiniHUD|0.39.6 → 0.41.2|2026-09-27",
         "Placeholder API|3.0.0+26.1 → 3.2.0+26.3|2026-09-09",
         "Servux|0.10.3 → 0.12.2|2026-09-27",
         "spark|1.10.173-fabric → 1.10.187-fabric|2026-09-19",
         "Syncmatica|0.3.18 → 0.3.20|2026-09-22",
         "Tweakeroo|0.28.5 → 0.30.1|2026-09-27"]

rows: list[Row] = []
for n, v, d, why in BLOCKED:
    rows.append(Row(n, "blocked", v, d, reason=why))
for n, v, d, av in PRERELEASE:
    rows.append(Row(n, "prerelease", v, d, available=av))
for n, v, d, av in DEGRADED:
    rows.append(Row(n, "degraded", v, d, available=av))
for spec in READY:
    n, v, d = spec.split("|")
    rows.append(Row(n, "ready", v, d))

class Demo:
    def profiles(self): return [("服务器A", 30)]
    def versions(self): return ["26.3（最新正式版）", "26.2", "26.1"]
    def run(self, *a, **k): return ("", [])

app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(__import__("modcheck.gui.theme", fromlist=["QSS"]).QSS)
w = MainWindow(Demo())
w.resize(1180, 900)
app.processEvents()
w._rows = rows
w._render("❌  现在还不能升级到 Minecraft 26.3 —— 30 个模组中有 2 个阻塞、0 个未判定")
w.lb_progress.setText("检查完成，共 30 个模组")
w.lb_eta.setText("用时 15 秒 · 请求 46 次")
w.bar.setRange(0, 30); w.bar.setValue(30)
w.lb_status.setText("配置目录：D:\\…\\config   ·   Modrinth 已启用")
app.processEvents()
out = ROOT / "docs" / "design" / "gui_main.png"
w.grab().save(str(out))
print("已渲染:", out)
