@echo off
setlocal
set "ROOT=%~dp0"
if defined MODCHECK_PYTHON (set "PY=%MODCHECK_PYTHON%") else if exist "%ROOT%.toolchain\Python311\python.exe" (set "PY=%ROOT%.toolchain\Python311\python.exe") else (set "PY=python")
set "PYTHONPATH=%ROOT%src"
set "PYTHONIOENCODING=utf-8"
"%PY%" -m modcheck %*
