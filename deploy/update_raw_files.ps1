# FAST update: download code via GitHub commit SHA (не кэш /main).
#
#   powershell -ExecutionPolicy Bypass -File deploy\update_raw_files.ps1

$ErrorActionPreference = "Stop"
$Root = "C:\firmy"
$Repo = "kakophoni4/sfgbdsgh"
$files = @(
    "run_parser.py",
    "smoke_check.py",
    "check_sources.py",
    "config.py",
    "requirements.txt",
    "parser/score.py",
    "parser/job_status.py",
    "parser/export_excel.py",
    "parser/export_gsheets.py",
    "parser/export_apps_script.py",
    "deploy/apps_script_sheets.js",
    "deploy/setup_apps_script.ps1",
    "deploy/show_status.ps1",

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
    "parser/enrich/zsk_bot.py",
    "parser/enrich/http_util.py",
    "parser/enrich/proxy_pool.py",
    "deploy/update_raw_files.ps1",
    "deploy/run_job.ps1",
    "deploy/register_task.ps1",
    "deploy/enrich_loop.ps1",
    "deploy/fresh_run.ps1",
    "tools/rotate_proxy_session.py",
    "tools/probe_v_sources.py",
    "tools/audit_proverit.py",
    "tools/cleanup_bad_egrul.py"
)

if (-not (Test-Path $Root)) { throw "Missing $Root" }
Set-Location $Root

# Актуальный SHA main — raw по /main часто кэшируется со старым содержимым
$shaResp = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/commits/main" -Headers @{
    "User-Agent" = "firmy-updater"
    "Accept"     = "application/vnd.github+json"
}
$sha = [string]$shaResp.sha
if (-not $sha -or $sha.Length -lt 7) { throw "Cannot resolve main SHA from GitHub API" }
Write-Host "main SHA: $sha"

$Base = "https://raw.githubusercontent.com/$Repo/$sha"
$n = 0
foreach ($rel in $files) {
    $url = "$Base/$rel"
    $out = Join-Path $Root ($rel -replace "/", "\")
    $dir = Split-Path $out -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    try {
        Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing -TimeoutSec 60 -Headers @{
            "User-Agent" = "firmy-updater"
        }
        # PowerShell 5.1 needs UTF-8 BOM for .ps1 with non-ASCII, else parser breaks
        if ($rel -like "*.ps1") {
            $txt = [System.IO.File]::ReadAllText($out)
            $utf8Bom = New-Object System.Text.UTF8Encoding $true
            [System.IO.File]::WriteAllText($out, $txt, $utf8Bom)
        }
        $n++
        Write-Host ("OK " + $rel)
    } catch {
        try {
            $alt = "https://cdn.jsdelivr.net/gh/$Repo@$sha/$rel"
            Invoke-WebRequest -Uri $alt -OutFile $out -UseBasicParsing -TimeoutSec 60
            if ($rel -like "*.ps1") {
                $txt = [System.IO.File]::ReadAllText($out)
                $utf8Bom = New-Object System.Text.UTF8Encoding $true
                [System.IO.File]::WriteAllText($out, $txt, $utf8Bom)
            }
            $n++
            Write-Host ("OK(jsdelivr) " + $rel)
        } catch {
            Write-Host ("SKIP " + $rel + " :: " + $_.Exception.Message)
        }
    }
}
Write-Host ("Done: $n files from $sha. No data/venv touched.")
