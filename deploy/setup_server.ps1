# Установка на Windows Server.
# Запуск из корня проекта (PowerShell от админа желательно):
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\deploy\setup_server.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "==> Каталог: $Root"

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "Python не найден. Поставь Python 3.11+ с python.org и отметь Add to PATH."
    exit 1
}

python --version

if (-not (Test-Path ".venv")) {
    Write-Host "==> Создаю venv"
    python -m venv .venv
}

$pip = Join-Path $Root ".venv\Scripts\pip.exe"
$pyVenv = Join-Path $Root ".venv\Scripts\python.exe"

& $pip install -U pip
& $pip install -r requirements.txt

New-Item -ItemType Directory -Force -Path "data" | Out-Null

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Создан .env — проверь TELEGRAM_PHONE и ENRICH_PAUSE"
}

Write-Host ""
Write-Host "==> Smoke-check сайтов ФНС"
& $pyVenv smoke_check.py

Write-Host ""
Write-Host "Дальше:"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "  python telegram_login.py"
Write-Host "  python run_parser.py --limit 300"
Write-Host "  python run_parser.py --enrich-only --enrich-limit 20"
Write-Host "  # расписание: .\deploy\register_task.ps1"
