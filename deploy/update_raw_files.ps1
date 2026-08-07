# FAST update: download only code files via raw.githubusercontent.com
# No zip, no backup of data/venv. ~10-20 sec.
#
#   powershell -ExecutionPolicy Bypass -File deploy\update_raw_files.ps1

$ErrorActionPreference = "Stop"
$Root = "C:\firmy"
$Base = "https://raw.githubusercontent.com/kakophoni4/sfgbdsgh/main"
$files = @(
    "run_parser.py",
    "smoke_check.py",
    "check_sources.py",
    "config.py",
    "requirements.txt",
    "parser/score.py",
    "parser/export_excel.py",
    "parser/export_gsheets.py",
    "parser/export_apps_script.py",
    "deploy/apps_script_sheets.js",
    "deploy/setup_apps_script.ps1",


    "parser/scrape.py",
    "parser/dedup.py",
    "parser/db.py",
    "parser/extract.py",
    "parser/enrich/pipeline.py",
    "parser/enrich/egrul.py",
    "parser/enrich/buh.py",
    "parser/enrich/kad.py",
    "parser/enrich/kad_browser.py",
    "parser/enrich/companium.py",
    "parser/enrich/checko.py",
    "parser/enrich/saby.py",
    "parser/enrich/fssp.py",
    "parser/enrich/fedresurs.py",
    "parser/enrich/unreliable.py",
    "parser/enrich/http_util.py",
    "parser/enrich/proxy_pool.py",
    "deploy/update_raw_files.ps1",
    "deploy/run_job.ps1",
    "deploy/register_task.ps1",
    "deploy/enrich_loop.ps1",
    "deploy/fresh_run.ps1",
    "tools/rotate_proxy_session.py",
    "tools/probe_v_sources.py",
    "tools/audit_proverit.py"
)

if (-not (Test-Path $Root)) { throw "Missing $Root" }
Set-Location $Root
$n = 0
foreach ($rel in $files) {
    $url = "$Base/$rel"
    $out = Join-Path $Root ($rel -replace "/", "\")
    $dir = Split-Path $out -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    try {
        Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing -TimeoutSec 60
        $n++
        Write-Host ("OK " + $rel)
    } catch {
        Write-Host ("SKIP " + $rel + " :: " + $_.Exception.Message)
    }
}
Write-Host ("Done: $n files. No data/venv touched.")
