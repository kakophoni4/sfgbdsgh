# Catch up enrich for many INNs (repeat until almost no work).
#   powershell -ExecutionPolicy Bypass -File deploy\enrich_loop.ps1
#   powershell -ExecutionPolicy Bypass -File deploy\enrich_loop.ps1 -Rounds 15 -EnrichLimit 80

param(
    [int]$Rounds = 12,
    [int]$EnrichLimit = 80
)

$ErrorActionPreference = "Stop"
$Root = "C:\firmy"
if (-not (Test-Path $Root)) {
    $Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
Set-Location $Root
$py = Join-Path $Root ".venv\Scripts\python.exe"

for ($i = 1; $i -le $Rounds; $i++) {
    Write-Host ("==> Enrich round " + $i + "/" + $Rounds)
    & $py run_parser.py --enrich-core --enrich-limit $EnrichLimit
    if ($LASTEXITCODE -ne 0) { throw "enrich failed" }
}

Write-Host "==> Rescore + export"
& $py run_parser.py --rescore --export-only
Write-Host "Done. Repeat later if gaps remain."
