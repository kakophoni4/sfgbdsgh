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
        -Description "Serve lavok_parser.xlsx for CRM pull on :8788" `
        -Force | Out-Null
} catch {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Serve lavok_parser.xlsx for CRM pull on :8788" `
        -Force | Out-Null
}

# Firewall: only CRM IP
$ruleName = "Lavok export $port"
try { netsh advfirewall firewall delete rule name="$ruleName" | Out-Null } catch {}
netsh advfirewall firewall add rule name="$ruleName" dir=in action=allow protocol=TCP localport=$port remoteip=$crmIp | Out-Null

# Large Send Offload: body may not leave NIC (CRM sees headers, 0 body)
Get-NetAdapter | Where-Object { $_.Status -eq "Up" } | ForEach-Object {
    try {
        Disable-NetAdapterLso -Name $_.Name -Confirm:$false -ErrorAction Stop
        Write-Host ("  LSO off: " + $_.Name)
    } catch {}
}

Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 2

Write-Host ("OK: task '" + $taskName + "' started.")
Write-Host ("  Listen:  http://0.0.0.0:" + $port + "/lavok/export.xlsx")
Write-Host ("  Allow:   remote IP " + $crmIp)
Write-Host "  Header:  X-Lavok-Ingest-Token"

try {
    $pub = (Invoke-RestMethod -Uri "https://api.ipify.org" -TimeoutSec 10)
    Write-Host ("  Public:  http://" + $pub + ":" + $port + "/lavok/export.xlsx")
    Write-Host "Send CRM this URL + token from .env"
} catch {
    Write-Host "  Public IP: (lookup failed) - check on the host and send to CRM"
}

try {
    $h = Invoke-WebRequest -Uri ("http://127.0.0.1:" + $port + "/healthz") -UseBasicParsing -TimeoutSec 5
    Write-Host ("  healthz: " + $h.StatusCode)
} catch {
    Write-Host ("  healthz: FAIL - check task/logs: " + $_.Exception.Message)
}

# Range smoke via curl.exe (PowerShell blocks Range header)
$token = ""
$envFile = Join-Path $Root ".env"
if (Test-Path $envFile) {
    $m = Select-String -Path $envFile -Pattern "(?m)^\s*LAVOK_INGEST_TOKEN=(.+)$" | Select-Object -First 1
    if ($m) { $token = $m.Matches[0].Groups[1].Value.Trim() }
}
if ($token) {
    $tmpOut = Join-Path $env:TEMP "lavok_range_smoke.bin"
    $tmpHdr = Join-Path $env:TEMP "lavok_range_smoke.hdr"
    try {
        $null = & curl.exe -sS -D $tmpHdr -o $tmpOut `
            -H ("X-Lavok-Ingest-Token: " + $token) `
            -H "Range: bytes=0-1023" `
            ("http://127.0.0.1:" + $port + "/lavok/export.xlsx") `
            --connect-timeout 10 --max-time 20
        $status = 0
        if (Test-Path $tmpHdr) {
            $first = Get-Content $tmpHdr -TotalCount 1
            if ($first -match "HTTP/\S+\s+(\d+)") { $status = [int]$Matches[1] }
        }
        $len = 0
        if (Test-Path $tmpOut) { $len = (Get-Item $tmpOut).Length }
        Write-Host ("  range:   HTTP " + $status + ", body=" + $len + " bytes (expect 206 / 1024)")
        if ($status -eq 206 -and $len -eq 1024) {
            Write-Host "  range:   OK"
        }
    } catch {
        Write-Host ("  range:   FAIL - " + $_.Exception.Message)
    } finally {
        Remove-Item $tmpOut, $tmpHdr -Force -ErrorAction SilentlyContinue
    }
} else {
    Write-Host "  range:   skipped (no LAVOK_INGEST_TOKEN in .env)"
}
