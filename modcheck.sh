#!/usr/bin/env sh
# modcheck 启动脚本（Linux / macOS）
ROOT="$(cd "$(dirname "$0")" && pwd)"
if [ -n "$MODCHECK_PYTHON" ]; then
  PY="$MODCHECK_PYTHON"
elif [ -x "$ROOT/.toolchain/Python311/python.exe" ]; then
  PY="$ROOT/.toolchain/Python311/python.exe"
else
  PY=python3
fi
PYTHONPATH="$ROOT/src" PYTHONIOENCODING=utf-8 exec "$PY" -m modcheck "$@"
