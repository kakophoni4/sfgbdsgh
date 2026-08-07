# Один прогон: scrape + enrich + excel (для Планировщика заданий)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $py = "python"
}

$logDir = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("run_{0:yyyyMMdd_HHmmss}.log" -f (Get-Date))

& $py run_parser.py --enrich --limit 300 --enrich-limit 40 *>&1 | Tee-Object -FilePath $log
exit $LASTEXITCODE
