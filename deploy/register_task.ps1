# Register FirmParser scheduled task (run as Admin if possible).
# While a run is active, new starts are skipped (IgnoreNew + mutex in run_job.ps1).
#
#   powershell -ExecutionPolicy Bypass -File deploy\register_task.ps1
#   powershell -ExecutionPolicy Bypass -File deploy\register_task.ps1 -EveryMinutes 5
#   powershell -ExecutionPolicy Bypass -File deploy\register_task.ps1 -EveryMinutes 30

param(
    [ValidateSet(5, 10, 15, 30, 60)]
    [int]$EveryMinutes = 5
)

$ErrorActionPreference = "Stop"
$Root = "C:\firmy"
if (-not (Test-Path (Join-Path $Root "run_parser.py"))) {
    $Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$script = Join-Path $Root "deploy\run_job.ps1"
$taskName = "FirmParser"

if (-not (Test-Path $script)) {
    throw "Missing $script - run update_raw_files.ps1 first"
}

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory $Root

$triggerRepeat = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) `
    -RepetitionDuration ([TimeSpan]::MaxValue)
$triggerBoot = New-ScheduledTaskTrigger -AtStartup
$triggers = @($triggerRepeat, $triggerBoot)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 8) `
    -MultipleInstances IgnoreNew `
    -RestartCount 0

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

$desc = "Firm parser: TG -> enrich(no limit) -> Excel/Sheets. Skip if running."

try {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $triggers `
        -Settings $settings `
        -Principal $principal `
        -Description $desc `
        -Force | Out-Null
} catch {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $triggers `
        -Settings $settings `
        -Description $desc `
        -Force | Out-Null
}

Write-Host "OK: task '$taskName' every $EveryMinutes min + at Windows startup."
Write-Host "  MultipleInstances=IgnoreNew (second instance will not start)."
Write-Host "  Execution time limit: 8 hours."
Write-Host "Check:  Get-ScheduledTask -TaskName $taskName | Format-List *"
Write-Host "Start:  Start-ScheduledTask -TaskName $taskName"
Write-Host "Stop:   Stop-ScheduledTask -TaskName $taskName"
Write-Host "Remove: Unregister-ScheduledTask -TaskName $taskName -Confirm:`$false"
Write-Host "Logs:   $Root\data\logs\"
Write-Host "Status: powershell -ExecutionPolicy Bypass -File $Root\deploy\show_status.ps1"
