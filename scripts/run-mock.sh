#!/usr/bin/env bash
# Offline mock pipeline run (POSIX). Equivalent to `make run-mock`.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=".venv/bin/python"; [ -x "$PY" ] || PY="python3"
SEED="${1:-cottagecore}"
COUNT="${2:-3}"
MOCK=1 exec "$PY" -m pod_autopilot.pipeline --seed "$SEED" --count "$COUNT"
