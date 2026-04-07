#!/usr/bin/env bash
set -euo pipefail

if ! command -v ruff >/dev/null 2>&1; then
  echo "ruff is not installed. Activate the project virtualenv and run: python -m pip install -e '.[dev]'" >&2
  exit 127
fi

ruff format .
ruff check --fix .
