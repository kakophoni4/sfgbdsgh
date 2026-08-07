# Регистрация задания в Планировщике Windows (каждые 6 часов).
# Запуск от администратора:
#   .\deploy\register_task.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$script = Join-Path $Root "deploy\run_job.ps1"
$taskName = "FirmParser"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory $Root

$trigger = @(
    (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Hours 6) -RepetitionDuration ([TimeSpan]::MaxValue)),
    (New-ScheduledTaskTrigger -AtStartup)
)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Парсер продажи ООО: Telegram + ЕГРЮЛ/БФО" `
    -Force | Out-Null

Write-Host "Задание '$taskName' зарегистрировано (каждые 6ч + при старте)."
Write-Host "Проверка: Get-ScheduledTask -TaskName $taskName"
Write-Host "Ручной запуск: Start-ScheduledTask -TaskName $taskName"
Write-Host "Логи: $Root\data\logs\"
