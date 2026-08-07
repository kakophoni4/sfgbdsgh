# Update C:\firmy from GitHub zip (no git required).
# Run:
#   powershell -ExecutionPolicy Bypass -File deploy\update_from_github.ps1

$ErrorActionPreference = "Stop"
$RepoZip = "https://github.com/kakophoni4/sfgbdsgh/archive/refs/heads/main.zip"
$Target = "C:\firmy"

Write-Host "==> Download $RepoZip"
$tmpZip = Join-Path $env:TEMP "firmy_main.zip"
$tmpDir = Join-Path $env:TEMP "firmy_main_unpack"
if (Test-Path $tmpZip) { Remove-Item $tmpZip -Force }
if (Test-Path $tmpDir) { Remove-Item $tmpDir -Recurse -Force }

Invoke-WebRequest -Uri $RepoZip -OutFile $tmpZip -UseBasicParsing
Expand-Archive -Path $tmpZip -DestinationPath $tmpDir -Force

$src = Get-ChildItem $tmpDir -Directory | Select-Object -First 1
if (-not $src) { throw "Archive folder not found" }

# Keep secrets / venv / data across update
$keep = @(".env", "telegram_session.session", ".venv", "data")
$backup = Join-Path $env:TEMP "firmy_keep_backup"
if (Test-Path $backup) { Remove-Item $backup -Recurse -Force }
New-Item -ItemType Directory -Path $backup | Out-Null

if (Test-Path $Target) {
    foreach ($name in $keep) {
        $p = Join-Path $Target $name
        if (Test-Path $p) {
            Copy-Item $p -Destination (Join-Path $backup $name) -Recurse -Force
            Write-Host ("  backup " + $name)
        }
    }
} else {
    New-Item -ItemType Directory -Path $Target | Out-Null
}

Write-Host ("==> Copy code to " + $Target)
Copy-Item -Path (Join-Path $src.FullName "*") -Destination $Target -Recurse -Force

foreach ($name in $keep) {
    $p = Join-Path $backup $name
    if (Test-Path $p) {
        Copy-Item $p -Destination (Join-Path $Target $name) -Recurse -Force
        Write-Host ("  restore " + $name)
    }
}

Write-Host ("==> Done: " + $Target)
Write-Host "Next:"
Write-Host ("  cd " + $Target)
Write-Host '  .\.venv\Scripts\Activate.ps1'
Write-Host '  python smoke_check.py'
Write-Host '  python run_parser.py --rescore'
Write-Host '  python run_parser.py --enrich-kad --enrich-fssp --enrich-fedresurs --enrich-limit 20'
Write-Host '  python run_parser.py --export-only'
