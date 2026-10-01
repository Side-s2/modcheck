@echo off
REM modcheck CLI launcher (ASCII only: cmd.exe runs in the OEM codepage and
REM Chinese comments here would render as mojibake - learned the hard way).
cd /d "%~dp0"
modcheck\modcheck.exe
echo.
pause
