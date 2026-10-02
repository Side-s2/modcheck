@echo off
REM modcheck CLI launcher. ASCII only: cmd.exe runs in the OEM codepage
REM and non-ASCII comments would show up as mojibake.
cd /d "%~dp0"
modcheck\modcheck.exe
echo.
pause
