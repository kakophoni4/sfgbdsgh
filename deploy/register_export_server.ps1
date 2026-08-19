# Keep HTTP export of lavok_parser.xlsx running (CRM pulls every 5 min).
#
#   powershell -ExecutionPolicy Bypass -File deploy\register_export_server.ps1

$ErrorActionPreference = "Stop"
$Root = "C:\firmy"
if (-not (Test-Path (Join-Path $Root "run_parser.py"))) {
    $Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$taskName = "FirmParserExport"

$action = New-ScheduledTaskAction `
    -Execute $py `
    -Argument "-m parser.serve_export" `
    -WorkingDirectory $Root

$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
try {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "Serve C:\firmy\data\lavok_parser.xlsx for CRM pull" `
        -Force | Out-Null
} catch {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Serve C:\firmy\data\lavok_parser.xlsx for CRM pull" `
        -Force | Out-Null
}

try {
    netsh advfirewall firewall delete rule name="Lavok export 8788" | Out-Null
} catch {}
netsh advfirewall firewall add rule name="Lavok export 8788" dir=in action=allow protocol=TCP localport=8788 | Out-Null

Start-ScheduledTask -TaskName $taskName
Write-Host "OK: task '$taskName' is running."
Write-Host "  GET http://<this-host>:8788/lavok/export.xlsx"
Write-Host "  Header: X-Lavok-Ingest-Token"
Write-Host "Give CRM this URL (public IP or DNS), then they set LAVOK_PARSER_PULL_URL."
