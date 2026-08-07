# Обновление проекта БЕЗ git: скачивает zip с GitHub.
# Запуск:
#   powershell -ExecutionPolicy Bypass -File deploy\update_from_github.ps1
# Или с нуля на сервере:
#   powershell -ExecutionPolicy Bypass -File update_from_github.ps1
#   (если скрипта ещё нет — см. блок внину README / команды вручную)

$ErrorActionPreference = "Stop"
$RepoZip = "https://github.com/kakophoni4/sfgbdsgh/archive/refs/heads/main.zip"
$Target = "C:\firmy"

Write-Host "==> Качаю $RepoZip"
$tmpZip = Join-Path $env:TEMP "firmy_main.zip"
$tmpDir = Join-Path $env:TEMP "firmy_main_unpack"
if (Test-Path $tmpZip) { Remove-Item $tmpZip -Force }
if (Test-Path $tmpDir) { Remove-Item $tmpDir -Recurse -Force }

Invoke-WebRequest -Uri $RepoZip -OutFile $tmpZip -UseBasicParsing
Expand-Archive -Path $tmpZip -DestinationPath $tmpDir -Force

$src = Get-ChildItem $tmpDir -Directory | Select-Object -First 1
if (-not $src) { throw "Не нашёл папку в архиве" }

# сохраняем секреты и venv/data
$keep = @(".env", "telegram_session.session", ".venv", "data")
$backup = Join-Path $env:TEMP "firmy_keep_backup"
if (Test-Path $backup) { Remove-Item $backup -Recurse -Force }
New-Item -ItemType Directory -Path $backup | Out-Null

if (Test-Path $Target) {
    foreach ($name in $keep) {
        $p = Join-Path $Target $name
        if (Test-Path $p) {
            Copy-Item $p -Destination (Join-Path $backup $name) -Recurse -Force
            Write-Host "  backup $name"
        }
    }
    # не удаляем весь Target целиком если занят — копируем поверх
} else {
    New-Item -ItemType Directory -Path $Target | Out-Null
}

Write-Host "==> Копирую код в $Target"
Copy-Item -Path (Join-Path $src.FullName "*") -Destination $Target -Recurse -Force

foreach ($name in $keep) {
    $p = Join-Path $backup $name
    if (Test-Path $p) {
        Copy-Item $p -Destination (Join-Path $Target $name) -Recurse -Force
        Write-Host "  restore $name"
    }
}

Write-Host "==> Готово: $Target"
Write-Host "Дальше:"
Write-Host "  cd $Target"
Write-Host "  .\.venv\Scripts\Activate.ps1   # или .\deploy\setup_server.ps1 если venv нет"
Write-Host "  python smoke_check.py"
