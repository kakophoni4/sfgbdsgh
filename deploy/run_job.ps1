# Hourly job: recent scrape + enrich gaps + excel (+ optional Google Sheets)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

$logDir = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("run_{0:yyyyMMdd_HHmmss}.log" -f (Get-Date))

$useApps = $false
$useSheets = $false
$envFile = Join-Path $Root ".env"
if (Test-Path $envFile) {
    $envText = Get-Content $envFile -Raw -ErrorAction SilentlyContinue
    if ($envText -match "GOOGLE_APPS_SCRIPT_URL=\S+") { $useApps = $true }
    elseif ($envText -match "GOOGLE_SHEETS_ID=\S+") { $useSheets = $true }
}

Write-Host "==> scrape 2d + enrich-core"
$cmd1 = @("run_parser.py", "--since-days", "2", "--limit", "3000", "--enrich-core", "--enrich-limit", "40")
if ($useApps) { $cmd1 += "--export-apps-script" }
elseif ($useSheets) { $cmd1 += "--export-gsheets" }
& $py @cmd1 *>&1 | Tee-Object -FilePath $log
$code = $LASTEXITCODE

Write-Host "==> rescore + export"
$cmd2 = @("run_parser.py", "--rescore", "--export-only")
if ($useApps) { $cmd2 += "--export-apps-script" }
elseif ($useSheets) { $cmd2 += "--export-gsheets" }
& $py @cmd2 *>&1 | Tee-Object -FilePath $log -Append

Write-Host ("Log: " + $log)
exit $code
