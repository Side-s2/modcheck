# -*- coding: utf-8 -*-
"""渲染二期对话框：清单管理 + 设置。"""
import os, sys, tempfile
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))
os.environ["QT_QPA_PLATFORM"] = "windows"

from PyQt6.QtWidgets import QApplication
from modcheck.gui import theme
from modcheck.gui.backend import CliBackend
from modcheck.gui.profiles_dialog import ProfilesDialog
from modcheck.gui.settings_dialog import SettingsDialog

cfg = Path(tempfile.mkdtemp(prefix="dlg-"))
# 造两份清单，让界面有真实内容
from modcheck.storage.profiles import new_profile, save_profile, profile_path
from modcheck.core.models import ModEntry, MatchStatus
for name, n in (("服务器A", 30), ("测试服", 8)):
    p = new_profile(name)
    for i in range(n):
        p.mods.append(ModEntry(key=f"slug:modrinth:mod{i}", display_name=f"Mod{i}",
                               mod_id=f"mod{i}", file_name=f"mod{i}-1.0.jar",
                               sources={"modrinth": f"mod{i}"}, match_status=MatchStatus.EXACT))
    save_profile(p, profile_path(cfg / "profiles", name))

app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(theme.QSS)
be = CliBackend(config_dir=cfg)

d1 = ProfilesDialog(be); d1.resize(980, 620)
for _ in range(3):          # setCellWidget 要等一轮布局才定位，否则截图会出现控件叠影假象
    app.processEvents()
d1.grab().save(str(ROOT / "docs" / "design" / "gui_profiles.png"))
print("已渲染: gui_profiles.png")

d2 = SettingsDialog(be); d2.resize(620, 460); app.processEvents()
d2.grab().save(str(ROOT / "docs" / "design" / "gui_settings.png"))
print("已渲染: gui_settings.png")
