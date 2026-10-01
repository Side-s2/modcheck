@echo off
rem Launcher for modcheck.exe -- double-click THIS file instead of the exe.
rem Keep this file pure ASCII: cmd.exe reads .cmd in the OEM codepage,
rem so non-ASCII comments turn into mojibake and can break parsing.
cd /d "%~dp0"
"%~dp0modcheck.exe" %*
if errorlevel 1 pause
