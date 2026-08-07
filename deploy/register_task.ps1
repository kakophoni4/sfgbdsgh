# Регистрация автозапуска (от Администратора).
# Пока идёт старый прогон — новый SKIP (IgnoreNew + mutex в run_job.ps1).
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
    throw "Не найден $script — сначала update_raw_files.ps1"
}

# снять старую задачу если была
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory $Root

# первый старт через 1 мин, дальше каждые N минут
$triggerRepeat = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) `
    -RepetitionDuration ([TimeSpan]::MaxValue)
$triggerBoot = New-ScheduledTaskTrigger -AtStartup
$triggers = @($triggerRepeat, $triggerBoot)

# IgnoreNew: пока крутится задача — новый экземпляр планировщик НЕ запускает
# + в run_job.ps1 свой mutex/lock на случай гонки
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

try {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $triggers `
        -Settings $settings `
        -Principal $principal `
        -Description "Firm parser: TG → enrich(без лимита) → Excel/Sheets. Skip if running." `
        -Force | Out-Null
} catch {
    # fallback без Highest (если не админ)
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $triggers `
        -Settings $settings `
        -Description "Firm parser: TG → enrich(без лимита) → Excel/Sheets. Skip if running." `
        -Force | Out-Null
}

Write-Host "OK: задача '$taskName' каждые $EveryMinutes мин + при старте Windows."
Write-Host "  MultipleInstances=IgnoreNew (второй не стартует)."
Write-Host "  Лимит выполнения: 8 часов."
Write-Host "Проверка:  Get-ScheduledTask -TaskName $taskName | Format-List *"
Write-Host "Сейчас:     Start-ScheduledTask -TaskName $taskName"
Write-Host "Стоп:       Stop-ScheduledTask -TaskName $taskName"
Write-Host "Удалить:    Unregister-ScheduledTask -TaskName $taskName -Confirm:`$false"
Write-Host "Логи:       $Root\data\logs\"
