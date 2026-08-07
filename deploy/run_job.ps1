# Автопрогон: TG → enrich всех уникальных дыр (limit=0) → Excel/Sheets.
# Второй экземпляр SKIP (mutex + lock).
# Живой статус: data\STATUS.txt  |  смотреть: deploy\show_status.ps1
#
#   powershell -ExecutionPolicy Bypass -File deploy\run_job.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (Test-Path "C:\firmy\run_parser.py") { $Root = "C:\firmy" }
Set-Location $Root

$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

$logDir = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$log = Join-Path $logDir ("run_{0}.log" -f $stamp)
$lockPath = Join-Path $Root "data\run_job.lock"
$statusTxt = Join-Path $Root "data\STATUS.txt"

function Write-Log([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding UTF8
}

function Set-JobStatus([string]$stage, [string]$detail = "") {
    $pyCode = @"
from parser.job_status import write_status
write_status(stage=$([char]39)$stage$([char]39), detail=$([char]39)$($detail.Replace("'"," "))$([char]39), extra={'log': r'$log'})
"@
    try {
        & $py -c $pyCode 2>$null
    } catch {
        # fallback без python
        $text = @"
Обновлено: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Этап:      $stage
Детали:    $detail
Лог:       $log
"@
        Set-Content -Path $statusTxt -Value $text -Encoding UTF8
    }
}

# --- блокировка ---
$mutex = New-Object System.Threading.Mutex($false, "Global\FirmParserRunJob")
$hasMutex = $false
$lockStream = $null
try {
    $hasMutex = $mutex.WaitOne(0)
} catch {
    $hasMutex = $false
}
if (-not $hasMutex) {
    Write-Host "SKIP: другой прогон уже работает (mutex)."
    try {
        & $py -c "from parser.job_status import mark_skip; mark_skip('mutex: already running')" 2>$null
    } catch {}
    exit 0
}

try {
    try {
        $lockStream = [System.IO.File]::Open(
            $lockPath,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
        $bytes = [Text.Encoding]::UTF8.GetBytes("pid=$PID started=$stamp`n")
        $lockStream.Write($bytes, 0, $bytes.Length)
        $lockStream.Flush()
    } catch {
        Write-Host "SKIP: другой прогон держит lock-файл."
        try {
            & $py -c "from parser.job_status import mark_skip; mark_skip('lock file held')" 2>$null
        } catch {}
        exit 0
    }

    $useApps = $false
    $useSheets = $false
    $envFile = Join-Path $Root ".env"
    if (Test-Path $envFile) {
        $envText = Get-Content $envFile -Raw -ErrorAction SilentlyContinue
        if ($envText -match "GOOGLE_APPS_SCRIPT_URL=\S+") { $useApps = $true }
        elseif ($envText -match "GOOGLE_SHEETS_ID=\S+") { $useSheets = $true }
    }

    Write-Log "START root=$Root apps=$useApps"
    Set-JobStatus "START" "pid=$PID log=$stamp"
    $code = 0

    # 1) TG — новые за 2 дня
    Set-JobStatus "scrape" "Telegram last 2 days"
    Write-Log "==> scrape Telegram (2d)"
    & $py run_parser.py --since-days 2 --limit 5000 *>&1 | Tee-Object -FilePath $log -Append
    if ($LASTEXITCODE -ne 0) { $code = $LASTEXITCODE }

    # 2) enrich всех уникальных дыр (без лимита), кругами
    $maxRounds = 20
    for ($i = 1; $i -le $maxRounds; $i++) {
        Set-JobStatus "enrich" ("round $i/$maxRounds unique INNs, limit=0")
        Write-Log ("==> enrich-core round {0}/{1} (уникальные, без лимита)" -f $i, $maxRounds)
        $enrichLog = Join-Path $logDir ("enrich_{0}_r{1}.log" -f $stamp, $i)
        & $py run_parser.py --enrich-only --enrich-core --enrich-limit 0 *>&1 |
            Tee-Object -FilePath $log -Append |
            Tee-Object -FilePath $enrichLog
        if ($LASTEXITCODE -ne 0) {
            $code = $LASTEXITCODE
            Write-Log "enrich exit=$LASTEXITCODE — продолжаем к экспорту"
            break
        }
        $tail = Get-Content $enrichLog -Raw -ErrorAction SilentlyContinue
        if ($tail -match "attempted.: 0") {
            Write-Log "enrich: attempted=0 — дыр не осталось"
            break
        }
        $zeroLines = ([regex]::Matches($tail, ":\s*0 шт")).Count
        $srcLines = ([regex]::Matches($tail, ":\s*\d+ шт")).Count
        if ($srcLines -gt 0 -and $zeroLines -ge $srcLines) {
            Write-Log "enrich: все источники 0 шт — готово"
            break
        }
    }

    # 3) export
    Set-JobStatus "export" "rescore + excel + sheets"
    Write-Log "==> rescore + export"
    $cmd = @("run_parser.py", "--rescore", "--export-only")
    if ($useApps) { $cmd += "--export-apps-script" }
    elseif ($useSheets) { $cmd += "--export-gsheets" }
    & $py @cmd *>&1 | Tee-Object -FilePath $log -Append
    if ($LASTEXITCODE -ne 0) { $code = $LASTEXITCODE }

    Write-Log ("DONE exit=$code log=$log")
    try {
        & $py -c "from parser.job_status import mark_done; mark_done('exit=$code')" 2>$null
    } catch {
        Set-JobStatus "DONE" "exit=$code"
    }
    exit $code
}
finally {
    if ($null -ne $lockStream) {
        try { $lockStream.Close() } catch {}
        try { $lockStream.Dispose() } catch {}
    }
    Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
    if ($hasMutex) {
        try { $mutex.ReleaseMutex() } catch {}
    }
    try { $mutex.Dispose() } catch {}
}
