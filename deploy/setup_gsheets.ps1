# Write Google Sheets id into C:\firmy\.env (keeps other lines).
#   powershell -ExecutionPolicy Bypass -File deploy\setup_gsheets.ps1

$ErrorActionPreference = "Stop"
$Root = "C:\firmy"
$SheetId = "1eI0e27z45BJJqB5sE3hgUlh7D9x_QbqsB_k7wVmgLqQ"
$KeyPath = Join-Path $Root "secrets\gsheets.json"
$EnvPath = Join-Path $Root ".env"

New-Item -ItemType Directory -Path (Join-Path $Root "secrets") -Force | Out-Null

$block = @"

# Google Sheets
GOOGLE_SHEETS_ID=$SheetId
GOOGLE_SERVICE_ACCOUNT_JSON=$KeyPath
"@

if (-not (Test-Path $EnvPath)) {
    Set-Content -Path $EnvPath -Value $block.Trim() -Encoding UTF8
} else {
    $text = Get-Content $EnvPath -Raw -Encoding UTF8
    if ($text -match "GOOGLE_SHEETS_ID=") {
        $text = [regex]::Replace($text, "(?m)^GOOGLE_SHEETS_ID=.*$", "GOOGLE_SHEETS_ID=$SheetId")
    } else {
        $text = $text.TrimEnd() + "`r`n" + $block
    }
    if ($text -match "GOOGLE_SERVICE_ACCOUNT_JSON=") {
        $text = [regex]::Replace($text, "(?m)^GOOGLE_SERVICE_ACCOUNT_JSON=.*$", "GOOGLE_SERVICE_ACCOUNT_JSON=$KeyPath")
    } elseif ($text -notmatch "GOOGLE_SERVICE_ACCOUNT_JSON=") {
        $text = $text.TrimEnd() + "`r`nGOOGLE_SERVICE_ACCOUNT_JSON=$KeyPath`r`n"
    }
    Set-Content -Path $EnvPath -Value $text.TrimEnd() -Encoding UTF8
}

Write-Host "Sheet id written to .env"
Write-Host "Put service-account JSON here: $KeyPath"
Write-Host "Share the spreadsheet with the client_email from that JSON (Editor)."
Write-Host ""
Write-Host "Then:"
Write-Host "  .\.venv\Scripts\pip.exe install gspread google-auth"
Write-Host "  .\.venv\Scripts\python.exe run_parser.py --export-only --export-gsheets"
