# Clean run on C:\firmy:
#   - update code from GitHub
#   - delete old data (DB + Excel); keep .env / session / venv
#   - scrape -> enrich-core -> rescore -> export
#
# Run:
#   powershell -ExecutionPolicy Bypass -File deploy\fresh_run.ps1
#   powershell -ExecutionPolicy Bypass -File deploy\fresh_run.ps1 -Limit 400 -EnrichLimit 80

param(
    [int]$Limit = 400,
    [int]$EnrichLimit = 80,
    [switch]$SkipUpdate,
    [switch]$SkipEnrich
)

$ErrorActionPreference = "Stop"
$Target = "C:\firmy"

if (-not (Test-Path $Target)) {
    throw "Missing folder $Target - run this on the server."
}

Set-Location $Target

if (-not $SkipUpdate) {
    Write-Host "==> Update code from GitHub"
    powershell -ExecutionPolicy Bypass -File (Join-Path $Target "deploy\update_from_github.ps1")
}

$venvPy = Join-Path $Target ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    throw "Missing $venvPy - create venv first."
}

Write-Host "==> Delete old data (keep .env, session, .venv)"
$data = Join-Path $Target "data"
New-Item -ItemType Directory -Path $data -Force | Out-Null
@(
    "listings.db",
    "listings.db-journal",
    "listings.db-wal",
    "listings.db-shm",
    "checklist_export.xlsx",
    "proxy_list_cache.txt"
) | ForEach-Object {
    $p = Join-Path $data $_
    if (Test-Path $p) {
        Remove-Item $p -Force
        Write-Host "  deleted $_"
    }
}
Get-ChildItem $data -Filter "checklist_export_*.xlsx" -ErrorAction SilentlyContinue |
    ForEach-Object {
        Remove-Item $_.FullName -Force
        Write-Host ("  deleted " + $_.Name)
    }

Write-Host "==> Check .env"
& $venvPy -c "from config import ENRICH_PROXY_LIST_URL, ENRICH_PROXY, ENRICH_PAUSE, ENRICH_LIMIT; print('LIST_URL', bool(ENRICH_PROXY_LIST_URL)); print('SINGLE_PROXY', bool(ENRICH_PROXY)); print('PAUSE', ENRICH_PAUSE, 'LIMIT', ENRICH_LIMIT)"

Write-Host "==> Scrape last $Limit messages"
& $venvPy run_parser.py --limit $Limit
if ($LASTEXITCODE -ne 0) { throw "scrape failed: $LASTEXITCODE" }

if (-not $SkipEnrich) {
    Write-Host "==> Enrich-core batch $EnrichLimit"
    & $venvPy run_parser.py --enrich-core --enrich-limit $EnrichLimit
    if ($LASTEXITCODE -ne 0) { throw "enrich failed: $LASTEXITCODE" }
}

Write-Host "==> Rescore + export"
& $venvPy run_parser.py --rescore
& $venvPy run_parser.py --export-only

Write-Host "==> Done"
Write-Host ("Excel: " + (Join-Path $data "checklist_export.xlsx"))
Write-Host "If gaps remain, run again:"
Write-Host ("  .\.venv\Scripts\python.exe run_parser.py --enrich-core --enrich-limit " + $EnrichLimit)
Write-Host "  .\.venv\Scripts\python.exe run_parser.py --rescore"
Write-Host "  .\.venv\Scripts\python.exe run_parser.py --export-only"
