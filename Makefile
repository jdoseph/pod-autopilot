# pod-autopilot dev tasks.
#
# Uses the project venv if present, else falls back to `python`.
# On Windows without `make`, use the scripts/ equivalents:
#   scripts\test.ps1   /  scripts\run-mock.ps1
# or on a POSIX box:
#   scripts/test.sh    /  scripts/run-mock.sh

ifeq ($(OS),Windows_NT)
  PY := .venv/Scripts/python.exe
else
  PY := .venv/bin/python
endif

SEED  ?= cottagecore
COUNT ?= 3

.PHONY: test run-mock install

install:
	$(PY) -m pip install -r requirements.txt

test:
	$(PY) -m pytest

# Fully offline pipeline run (no network, no spend, review-first).
run-mock:
	MOCK=1 $(PY) -m pod_autopilot.pipeline --seed "$(SEED)" --count $(COUNT)
