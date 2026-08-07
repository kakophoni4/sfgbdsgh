# Автопрогон: TG scrape → enrich без лимита → Excel + Google Sheets.
# Если уже идёт другой прогон — выходим сразу (файл-лок + Mutex).
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

function Write-Log([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding UTF8
}

# --- блокировка: второй экземпляр не стартует ---
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
    $code = 0

    # 1) новые объявления из TG (последние 2 дня)
    Write-Log "==> scrape Telegram (2d)"
    & $py run_parser.py --since-days 2 --limit 5000 *>&1 | Tee-Object -FilePath $log -Append
    if ($LASTEXITCODE -ne 0) { $code = $LASTEXITCODE }

    # 2) обогащение без лимита, кругами пока есть работа
    $maxRounds = 20
    for ($i = 1; $i -le $maxRounds; $i++) {
        Write-Log ("==> enrich-core round {0}/{1} (limit=0 = все дыры)" -f $i, $maxRounds)
        $enrichLog = Join-Path $logDir ("enrich_{0}_r{1}.log" -f $stamp, $i)
        & $py run_parser.py --enrich-only --enrich-core --enrich-limit 0 *>&1 |
            Tee-Object -FilePath $log -Append |
            Tee-Object -FilePath $enrichLog
        if ($LASTEXITCODE -ne 0) {
            $code = $LASTEXITCODE
            Write-Log "enrich exit=$LASTEXITCODE — продолжаем к экспорту"
            break
        }
        # если в раунде почти ничего не сделали — стоп
        $tail = Get-Content $enrichLog -Raw -ErrorAction SilentlyContinue
        if ($tail -match "attempted.: 0") {
            Write-Log "enrich: attempted=0 — дыр не осталось"
            break
        }
        # эвристика: все источники по 0 шт
        $zeroLines = ([regex]::Matches($tail, ":\s*0 шт")).Count
        $srcLines = ([regex]::Matches($tail, ":\s*\d+ шт")).Count
        if ($srcLines -gt 0 -and $zeroLines -ge $srcLines) {
            Write-Log "enrich: все источники 0 шт — готово"
            break
        }
    }

    # 3) итог: rescore + Excel + Sheets (только когда всё сделано)
    Write-Log "==> rescore + export"
    $cmd = @("run_parser.py", "--rescore", "--export-only")
    if ($useApps) { $cmd += "--export-apps-script" }
    elseif ($useSheets) { $cmd += "--export-gsheets" }
    & $py @cmd *>&1 | Tee-Object -FilePath $log -Append
    if ($LASTEXITCODE -ne 0) { $code = $LASTEXITCODE }

    Write-Log ("DONE exit=$code log=$log")
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
