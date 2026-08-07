# Emergency update: pull key Python files via raw.githubusercontent.com
# Use if zip update script is broken on the server.
#   powershell -ExecutionPolicy Bypass -File deploy\update_raw_files.ps1

$ErrorActionPreference = "Stop"
$Root = "C:\firmy"
$Base = "https://raw.githubusercontent.com/kakophoni4/sfgbdsgh/main"
$files = @(
    "run_parser.py",
    "smoke_check.py",
    "PLAN.md",
    "SERVER.md",
    "parser/score.py",
    "parser/export_excel.py",
    "parser/enrich/pipeline.py",
    "parser/enrich/egrul.py",
    "parser/enrich/buh.py",
    "parser/enrich/kad.py",
    "parser/enrich/fssp.py",
    "parser/enrich/fedresurs.py",
    "parser/enrich/unreliable.py",
    "parser/enrich/http_util.py",
    "deploy/update_from_github.ps1"
)

Set-Location $Root
foreach ($rel in $files) {
    $url = "$Base/$rel"
    $out = Join-Path $Root ($rel -replace "/", "\")
    $dir = Split-Path $out -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    Write-Host ("GET " + $rel)
    Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing
}

Write-Host "OK. Check:"
Write-Host '  python run_parser.py --help'
