# Run the test suite (Windows). Equivalent to `make test`.
$ErrorActionPreference = "Stop"
$py = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "py" }
& $py -m pytest @args
