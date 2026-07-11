# Offline mock pipeline run (Windows). Equivalent to `make run-mock`.
param(
    [string]$Seed = "cottagecore",
    [int]$Count = 3
)
$ErrorActionPreference = "Stop"
$py = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "py" }
$env:MOCK = "1"
& $py -m pod_autopilot.pipeline --seed $Seed --count $Count
