# Launcher invoked by Windows Task Scheduler for a scheduled pod-autopilot run.
# Runs the runner entrypoint using the project venv, appends output to a dated log,
# and mirrors the runner's exit code so Task Scheduler can detect failures.
#
# Review-first by default. To auto-publish on a schedule, set AUTO_PUBLISH=1 in
# .env (the runner reads it) — this launcher does NOT force publishing.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot          # repo root (parent of scripts\)
$py   = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "py" }          # fall back to the launcher

$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("run-{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))

"==== $(Get-Date -Format o) starting scheduled run ====" | Out-File -Append -Encoding utf8 $log

# Seeds/cap/auto-publish come from .env (SEEDS, PER_RUN_CAP, AUTO_PUBLISH).
& $py -m pod_autopilot.runner *>> $log
$code = $LASTEXITCODE

"==== $(Get-Date -Format o) finished (exit $code) ====" | Out-File -Append -Encoding utf8 $log
exit $code
