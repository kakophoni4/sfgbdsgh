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

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
$wasRunning = $existing -and ($existing.State -eq "Running")

# -WindowStyle Hidden: без синего окна каждые 5 мин (лог всё равно в data\logs)
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory $Root

# TimeSpan.MaxValue is rejected by Task Scheduler (HRESULT 0x80041318).
$triggerRepeat = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 9999)
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

$registered = $false
if ($wasRunning) {
    # Unregister/Register -Force убивает текущий прогон — обновляем на месте
    Write-Host "WARN: FirmParser is Running - updating definition WITHOUT kill."
    try {
        Set-ScheduledTask `
            -TaskName $taskName `
            -Action $action `
            -Trigger $triggers `
            -Settings $settings `
            -Principal $principal `
            -Description $desc | Out-Null
        $registered = $true
    } catch {
        Set-ScheduledTask `
            -TaskName $taskName `
            -Action $action `
            -Trigger $triggers `
            -Settings $settings `
            -Description $desc | Out-Null
        $registered = $true
    }
} else {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    try {
        Register-ScheduledTask `
            -TaskName $taskName `
            -Action $action `
            -Trigger $triggers `
            -Settings $settings `
            -Principal $principal `
            -Description $desc `
            -Force | Out-Null
        $registered = $true
        Write-Host "Registered with Highest privileges."
    } catch {
        Write-Host ("Highest failed: " + $_.Exception.Message)
        Write-Host "Retry without Highest..."
        Register-ScheduledTask `
            -TaskName $taskName `
            -Action $action `
            -Trigger $triggers `
            -Settings $settings `
            -Description $desc `
            -Force | Out-Null
        $registered = $true
    }
}

if (-not $registered) { throw "Failed to register task $taskName" }

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
$info = Get-ScheduledTaskInfo -TaskName $taskName
Write-Host ""
Write-Host "OK: task '$taskName' is ACTIVE."
Write-Host ("  State:     " + $task.State)
Write-Host ("  Every:     " + $EveryMinutes + " min (+ at Windows startup)")
Write-Host ("  Action:    " + $script)
Write-Host ("  Next run:  " + $info.NextRunTime)
Write-Host ("  Last run:  " + $info.LastRunTime)
Write-Host ("  Last code: " + $info.LastTaskResult)
Write-Host ""
Write-Host "Manual start now:"
Write-Host "  Start-ScheduledTask -TaskName $taskName"
Write-Host "Watch progress:"
Write-Host "  powershell -ExecutionPolicy Bypass -File $Root\deploy\show_status.ps1"
Write-Host "Logs:"
Write-Host "  $Root\data\logs\"
