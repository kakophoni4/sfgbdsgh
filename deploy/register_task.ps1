# Register Windows Scheduled Task (every 1 hour).
# Run as Administrator:
#   powershell -ExecutionPolicy Bypass -File deploy\register_task.ps1

$ErrorActionPreference = "Stop"
$Root = "C:\firmy"
if (-not (Test-Path $Root)) {
    $Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$script = Join-Path $Root "deploy\run_job.ps1"
$taskName = "FirmParser"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory $Root

$trigger = @(
    (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration ([TimeSpan]::MaxValue)),
    (New-ScheduledTaskTrigger -AtStartup)
)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Firm parser: Telegram scrape + enrich + Excel/Sheets hourly" `
    -Force | Out-Null

Write-Host "Task '$taskName' registered: every 1 hour + at startup."
Write-Host "Check: Get-ScheduledTask -TaskName $taskName"
Write-Host "Run now: Start-ScheduledTask -TaskName $taskName"
Write-Host "Logs: $Root\data\logs\"
