#!/usr/bin/env bash
# Run the test suite (POSIX). Equivalent to `make test`.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=".venv/bin/python"; [ -x "$PY" ] || PY="python3"
exec "$PY" -m pytest "$@"
