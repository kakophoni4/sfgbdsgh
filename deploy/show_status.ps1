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
$task = Get-ScheduledTask -TaskName "FirmParser" -ErrorAction SilentlyContinue
if ($task) {
    Write-Host ("Task: " + $task.State)
} else {
    Write-Host "Task: NOT REGISTERED"
}
if (Test-Path $lock) {
    Write-Host "Lock: RUNNING (data\run_job.lock exists)"
} else {
    Write-Host "Lock: idle (process not holding lock - if Stage=enrich and time old, it DIED)"
}
$venvPy = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*firmy*" -or $_.CommandLine -like "*run_parser*" }
if ($venvPy) {
    Write-Host ("Python: RUNNING pid=" + (($venvPy | ForEach-Object { $_.ProcessId }) -join ","))
} else {
    Write-Host "Python: not running"
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
