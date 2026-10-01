@echo off
rem 双击这个文件启动 modcheck（绕开 Explorer 直接启动 exe 时可能遇到的拦截）
rem 内容保持纯 ASCII —— cmd.exe 按系统代码页读取 .cmd，中文注释会变乱码并报错
cd /d "%~dp0"
"%~dp0modcheck.exe" %*
if errorlevel 1 pause
