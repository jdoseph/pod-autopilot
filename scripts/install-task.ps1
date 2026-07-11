# Register (or update) a Windows Task Scheduler job that runs pod-autopilot daily.
#
# Usage (from the repo root, in PowerShell):
#   .\scripts\install-task.ps1                 # daily at 09:00, review-first
#   .\scripts\install-task.ps1 -Time 07:30
#   .\scripts\install-task.ps1 -Uninstall
#
# The task runs run-scheduled.ps1, which invokes the runner using .env settings.
# No admin rights required: it registers under the current user and runs whether
# or not you're logged in (you'll be prompted once to store your password).

param(
    [string]$Time = "09:00",
    [string]$TaskName = "PodAutopilotDaily",
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$root     = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $root "scripts\run-scheduled.ps1"

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task '$TaskName'."
    return
}

if (-not (Test-Path $launcher)) { throw "launcher not found: $launcher" }

$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$launcher`""
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "pod-autopilot daily run (review-first unless AUTO_PUBLISH=1)" `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName' to run daily at $Time."
Write-Host "Inspect/run now with:  Start-ScheduledTask -TaskName $TaskName"
Write-Host "Logs: $($root)\logs\run-<date>.log"
