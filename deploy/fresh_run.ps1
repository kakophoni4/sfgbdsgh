# Чистый прогон на сервере C:\firmy:
#   - обновление кода с GitHub
#   - удаление старых data (БД + Excel), .env / session / venv НЕ трогаем
#   - scrape → enrich-core → rescore → export
#
# Запуск (от администратора не обязательно):
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
    throw "Нет каталога $Target — запускайте на сервере."
}

Set-Location $Target

if (-not $SkipUpdate) {
    Write-Host "==> Обновление кода с GitHub"
    powershell -ExecutionPolicy Bypass -File (Join-Path $Target "deploy\update_from_github.ps1")
}

$venvPy = Join-Path $Target ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    throw "Нет $venvPy — сначала setup / venv."
}

Write-Host "==> Удаление старых данных (оставляем .env, session, .venv)"
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
# старые копии excel при PermissionError
Get-ChildItem $data -Filter "checklist_export_*.xlsx" -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item $_.FullName -Force; Write-Host ("  deleted " + $_.Name) }

# проверить ключевые настройки
Write-Host "==> Проверка .env"
& $venvPy -c @"
from config import ENRICH_PROXY_LIST_URL, ENRICH_PROXY, ENRICH_PAUSE, ENRICH_LIMIT
print('ENRICH_PROXY_LIST_URL', bool(ENRICH_PROXY_LIST_URL))
print('ENRICH_PROXY single', bool(ENRICH_PROXY))
print('ENRICH_PAUSE', ENRICH_PAUSE, 'LIMIT', ENRICH_LIMIT)
"@

Write-Host "==> Scrape последних $Limit сообщений"
& $venvPy run_parser.py --limit $Limit
if ($LASTEXITCODE -ne 0) { throw "scrape failed: $LASTEXITCODE" }

if (-not $SkipEnrich) {
    Write-Host "==> Enrich-core (батч $EnrichLimit; при необходимости повторите)"
    & $venvPy run_parser.py --enrich-core --enrich-limit $EnrichLimit
    if ($LASTEXITCODE -ne 0) { throw "enrich failed: $LASTEXITCODE" }
}

Write-Host "==> Rescore + export"
& $venvPy run_parser.py --rescore
& $venvPy run_parser.py --export-only

Write-Host "==> Готово"
Write-Host ("Excel: " + (Join-Path $data "checklist_export.xlsx"))
Write-Host "Если остались дыры P/L/V — ещё раз:"
Write-Host ("  .\.venv\Scripts\python.exe run_parser.py --enrich-core --enrich-limit " + $EnrichLimit)
Write-Host "  .\.venv\Scripts\python.exe run_parser.py --rescore"
Write-Host "  .\.venv\Scripts\python.exe run_parser.py --export-only"
