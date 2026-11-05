#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "请先运行：python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt"
  exit 1
fi
exec .venv/bin/python server.py "$@"
