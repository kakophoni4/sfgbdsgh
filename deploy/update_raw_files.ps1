# FAST update: download code via GitHub commit SHA (не кэш /main).
#
#   powershell -ExecutionPolicy Bypass -File deploy\update_raw_files.ps1
#
# Сначала обновляет сам себя и перезапускается — иначе новые файлы
# из свежего списка не скачиваются (старый .ps1 крутит старый $files).

param(
    [switch]$Reloaded
)

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
    "parser/export_fingerprint.py",
    "parser/export_crm.py",
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

# Без этих файлов экспорт/парсер ломается — SKIP недопустим
$required = @(
    "run_parser.py",
    "config.py",
    "parser/export_crm.py",
    "parser/export_fingerprint.py",
    "parser/export_apps_script.py",
    "parser/export_excel.py",
    "deploy/run_job.ps1"
)

function Get-MainSha {
    $shaResp = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/commits/main" -Headers @{
        "User-Agent" = "firmy-updater"
        "Accept"     = "application/vnd.github+json"
    }
    $s = [string]$shaResp.sha
    if (-not $s -or $s.Length -lt 7) { throw "Cannot resolve main SHA from GitHub API" }
    return $s
}

function Save-RemoteFile {
    param(
        [string]$Sha,
        [string]$Rel
    )
    $Base = "https://raw.githubusercontent.com/$Repo/$Sha"
    $url = "$Base/$Rel"
    $out = Join-Path $Root ($Rel -replace "/", "\")
    $dir = Split-Path $out -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    try {
        Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing -TimeoutSec 60 -Headers @{
            "User-Agent" = "firmy-updater"
        }
    } catch {
        $alt = "https://cdn.jsdelivr.net/gh/$Repo@$Sha/$Rel"
        Invoke-WebRequest -Uri $alt -OutFile $out -UseBasicParsing -TimeoutSec 60
    }
    if ($Rel -like "*.ps1") {
        $txt = [System.IO.File]::ReadAllText($out)
        $utf8Bom = New-Object System.Text.UTF8Encoding $true
        [System.IO.File]::WriteAllText($out, $txt, $utf8Bom)
    }
    return $out
}

if (-not (Test-Path $Root)) { throw "Missing $Root" }
Set-Location $Root

$sha = Get-MainSha
Write-Host "main SHA: $sha"

# 1) сначала сам updater → перезапуск со свежим списком файлов
$selfRel = "deploy/update_raw_files.ps1"
$selfPath = Join-Path $Root ($selfRel -replace "/", "\")
$beforeHash = ""
if (Test-Path $selfPath) {
    $beforeHash = (Get-FileHash -Path $selfPath -Algorithm SHA256).Hash
}
Save-RemoteFile -Sha $sha -Rel $selfRel | Out-Null
$afterHash = (Get-FileHash -Path $selfPath -Algorithm SHA256).Hash
Write-Host ("OK " + $selfRel + " (bootstrap)")

if (-not $Reloaded -and $beforeHash -and ($beforeHash -ne $afterHash)) {
    Write-Host "Updater changed — reloading with fresh file list..."
    $argList = @(
        "-ExecutionPolicy", "Bypass",
        "-File", $selfPath,
        "-Reloaded"
    )
    $p = Start-Process -FilePath "powershell.exe" -ArgumentList $argList -Wait -PassThru -NoNewWindow
    exit $p.ExitCode
}

$n = 0
$failedRequired = @()
foreach ($rel in $files) {
    if ($rel -eq $selfRel) {
        # уже скачан выше
        $n++
        continue
    }
    try {
        Save-RemoteFile -Sha $sha -Rel $rel | Out-Null
        $n++
        Write-Host ("OK " + $rel)
    } catch {
        $msg = $_.Exception.Message
        Write-Host ("SKIP " + $rel + " :: " + $msg)
        if ($required -contains $rel) {
            $failedRequired += $rel
        }
    }
}

Write-Host ("Done: $n files from $sha. No data/venv touched.")
if ($failedRequired.Count -gt 0) {
    throw ("Required files failed: " + ($failedRequired -join ", "))
}
