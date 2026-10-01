@echo off
REM modcheck GUI launcher.
REM start is used so this console window closes at once: a GUI app should not
REM leave a black box behind it.
cd /d "%~dp0"
start "" "modcheck-gui\modcheck-gui.exe"
