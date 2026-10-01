# -*- coding: utf-8 -*-
"""决定性测试：真实 show() 之后再截图，看第一行的叠影是否消失。"""
import os, sys, tempfile
from pathlib import Path
ROOT = Path(r"D:\Programme\python_prgram\mod-version-checker")
sys.path.insert(0, str(ROOT / "src"))
os.environ["QT_QPA_PLATFORM"] = "windows"
from PyQt6.QtWidgets import QApplication
from modcheck.gui import theme
from modcheck.gui.backend import CliBackend
from modcheck.gui.profiles_dialog import ProfilesDialog
cfg = Path(tempfile.mkdtemp(prefix="dlg2-"))
from modcheck.storage.profiles import new_profile, save_profile, profile_path
from modcheck.core.models import ModEntry, MatchStatus
p = new_profile("服务器A")
for i in range(30):
    p.mods.append(ModEntry(key=f"slug:modrinth:mod{i}", display_name=f"Mod{i}", mod_id=f"mod{i}",
                           file_name=f"mod{i}-1.0.jar", sources={"modrinth": f"mod{i}"},
                           match_status=MatchStatus.EXACT))
save_profile(p, profile_path(cfg / "profiles", "服务器A"))

app = QApplication(sys.argv)
app.setStyle("Fusion"); app.setStyleSheet(theme.QSS)
d = ProfilesDialog(CliBackend(config_dir=cfg))
d.resize(980, 620)
d.show()                       # ← 关键：真实显示，让 Qt 完成布局
for _ in range(6):
    app.processEvents()
d.grab().save(str(ROOT / "docs" / "design" / "gui_profiles_shown.png"))
d.hide()
print("已渲染（show 之后）")
