# Quick status of current/last job run.
#   powershell -ExecutionPolicy Bypass -File deploy\show_status.ps1

$ErrorActionPreference = "Continue"
$Root = "C:\firmy"
if (-not (Test-Path (Join-Path $Root "run_parser.py"))) {
    $Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}

$statusTxt = Join-Path $Root "data\STATUS.txt"
$lock = Join-Path $Root "data\run_job.lock"
$logDir = Join-Path $Root "data\logs"

Write-Host "=== FirmParser status ==="
Write-Host ("Root: " + $Root)
if (Test-Path $lock) {
    Write-Host "Lock: RUNNING (data\run_job.lock exists)"
} else {
    Write-Host "Lock: idle"
}

Write-Host ""
if (Test-Path $statusTxt) {
    Get-Content $statusTxt -Encoding UTF8
} else {
    Write-Host "STATUS.txt not found yet - job has not written status."
}

Write-Host ""
Write-Host "=== last log (tail) ==="
if (Test-Path $logDir) {
    $last = Get-ChildItem $logDir -Filter "run_*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($last) {
        Write-Host ("File: " + $last.FullName)
        Get-Content $last.FullName -Tail 25 -Encoding UTF8
    } else {
        Write-Host "no run_*.log files"
    }
}
