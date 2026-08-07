# Собрать архив для заливки на сервер (Windows PowerShell)
# Запуск: powershell -ExecutionPolicy Bypass -File deploy\pack.ps1

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Stamp = Get-Date -Format "yyyyMMdd_HHmm"
$Out = Join-Path $Root "firmy_server_$Stamp.zip"

$include = @(
  "config.py",
  "tg_client.py",
  "telegram_login.py",
  "run_parser.py",
  "smoke_check.py",
  "requirements.txt",
  ".env.example",
  ".gitignore",
  "PLAN.md",
  "SERVER.md",
  "parser",
  "deploy"
)

# Опционально: сессия TG и .env (если есть)
$optional = @(".env", "telegram_session.session", "data")

$stage = Join-Path $env:TEMP "firmy_pack_$Stamp"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage | Out-Null

foreach ($item in $include) {
  $src = Join-Path $Root $item
  if (Test-Path $src) {
    Copy-Item $src -Destination (Join-Path $stage $item) -Recurse -Force
  }
}
foreach ($item in $optional) {
  $src = Join-Path $Root $item
  if (Test-Path $src) {
    Copy-Item $src -Destination (Join-Path $stage $item) -Recurse -Force
  }
}

if (Test-Path $Out) { Remove-Item $Out -Force }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $Out -Force
Remove-Item $stage -Recurse -Force

Write-Host "Архив: $Out"
Write-Host "Windows Server:"
Write-Host "  1) Скопируй zip на сервер, распакуй в C:\firmy"
Write-Host "  2) cd C:\firmy"
Write-Host "  3) .\deploy\setup_server.ps1"
Write-Host "  4) .\deploy\register_task.ps1   # расписание (от админа)"
