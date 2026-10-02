@echo off
REM modcheck GUI launcher. start is used so this console closes at once:
REM a GUI app should not leave a black box behind it.
cd /d "%~dp0"
start "" "modcheck-gui\modcheck-gui.exe"
