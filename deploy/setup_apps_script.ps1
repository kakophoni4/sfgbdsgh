# Добавить URL Apps Script в .env (без Google Cloud)
#
#   powershell -ExecutionPolicy Bypass -File deploy\setup_apps_script.ps1 -Url "https://script.google.com/macros/s/XXXX/exec"
#   powershell -ExecutionPolicy Bypass -File deploy\setup_apps_script.ps1 -Url "..." -Token "secret"

param(
    [Parameter(Mandatory = $true)][string]$Url,
    [string]$Token = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$envFile = Join-Path $Root ".env"
if (-not (Test-Path $envFile)) {
    New-Item -ItemType File -Path $envFile | Out-Null
}

$text = Get-Content $envFile -Raw -ErrorAction SilentlyContinue
if (-not $text) { $text = "" }

function Set-EnvLine([string]$content, [string]$key, [string]$value) {
    $line = "$key=$value"
    if ($content -match "(?m)^$key=") {
        return [regex]::Replace($content, "(?m)^$key=.*$", $line)
    }
    return $content.TrimEnd() + "`r`n$line`r`n"
}

$text = Set-EnvLine $text "GOOGLE_APPS_SCRIPT_URL" $Url
if ($Token) {
    $text = Set-EnvLine $text "GOOGLE_APPS_SCRIPT_TOKEN" $Token
}
Set-Content -Path $envFile -Value $text -Encoding UTF8

Write-Host "OK: GOOGLE_APPS_SCRIPT_URL записан в .env"
Write-Host "Проверка:"
Write-Host "  .\.venv\Scripts\python.exe run_parser.py --export-only --export-apps-script"
