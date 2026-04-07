#!/usr/bin/env bash
set -euo pipefail

if ! command -v pytest >/dev/null 2>&1; then
  echo "pytest is not installed. Activate the project virtualenv and run: python -m pip install -e '.[dev]'" >&2
  exit 127
fi

export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"

set +e
pytest "$@"
status=$?
set -e

if [ "$status" -eq 5 ]; then
  echo "pytest collected no tests; treating bootstrap state as success."
  exit 0
fi

exit "$status"
