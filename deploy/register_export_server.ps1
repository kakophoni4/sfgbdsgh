# Keep HTTP export of lavok_parser.xlsx running (CRM pulls every 5 min).
#
#   powershell -ExecutionPolicy Bypass -File deploy\register_export_server.ps1
#
# CRM pull:
#   GET http://<public-ip>:8788/lavok/export.xlsx
#   Header: X-Lavok-Ingest-Token: <same as .env>

$ErrorActionPreference = "Stop"
$Root = "C:\firmy"
if (-not (Test-Path (Join-Path $Root "run_parser.py"))) {
    $Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$taskName = "FirmParserExport"
$crmIp = "146.19.125.32"
$port = 8788

$action = New-ScheduledTaskAction `
    -Execute $py `
    -Argument "-m parser.serve_export" `
    -WorkingDirectory $Root

$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
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
        -Description "Serve C:\firmy\data\lavok_parser.xlsx for CRM pull on :8788" `
        -Force | Out-Null
} catch {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Serve C:\firmy\data\lavok_parser.xlsx for CRM pull on :8788" `
        -Force | Out-Null
}

# Firewall: only CRM IP
$ruleName = "Lavok export $port"
try { netsh advfirewall firewall delete rule name="$ruleName" | Out-Null } catch {}
netsh advfirewall firewall add rule name="$ruleName" dir=in action=allow protocol=TCP localport=$port remoteip=$crmIp | Out-Null

Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 2

Write-Host "OK: task '$taskName' started."
Write-Host ("  Listen:  http://0.0.0.0:{0}/lavok/export.xlsx" -f $port)
Write-Host ("  Allow:   remote IP {0}" -f $crmIp)
Write-Host "  Header:  X-Lavok-Ingest-Token"

# hint public IP for CRM
try {
    $pub = (Invoke-RestMethod -Uri "https://api.ipify.org" -TimeoutSec 10)
    Write-Host ("  Public:  http://{0}:{1}/lavok/export.xlsx" -f $pub, $port)
    Write-Host ("Send CRM this URL + token from .env")
} catch {
    Write-Host "  Public IP: (lookup failed) — check on the host and send to CRM"
}

# local smoke (no token => 403 is fine; healthz ok)
try {
    $h = Invoke-WebRequest -Uri ("http://127.0.0.1:{0}/healthz" -f $port) -UseBasicParsing -TimeoutSec 5
    Write-Host ("  healthz: {0}" -f $h.StatusCode)
} catch {
    Write-Host ("  healthz: FAIL — check task/logs: " + $_.Exception.Message)
}
