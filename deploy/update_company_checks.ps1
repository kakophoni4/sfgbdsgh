# Update company checks from one GitHub commit; preserve existing scheduled tasks.
$ErrorActionPreference = "Stop"
$Root = "C:\firmy"
$repo = "kakophoni4/sfgbdsgh"
$python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Parser venv not found in C:\firmy" }
Get-ScheduledTask -TaskName FirmParserExport -ErrorAction Stop | Out-Null
$sha = (Invoke-RestMethod "https://api.github.com/repos/$repo/commits/main" -Headers @{"User-Agent"="firmy-checks-update"}).sha
if ($sha -notmatch "^[a-f0-9]{40}$") { throw "Cannot resolve GitHub commit" }
$relativeFiles = @(
    "parser/company_checks.py", "parser/company_check_sources.py", "parser/check_process.py",
    "parser/export_company_checks.py", "parser/serve_export.py", "parser/enrich/buh.py",
    "parser/enrich/kad.py", "parser/enrich/fedresurs.py", "parser/enrich/zsk_bot.py",
    "deploy/update_raw_files.ps1"
)
$updateDir = Join-Path $Root ("data\code_updates\checks_" + [Guid]::NewGuid().ToString("N"))
$stageDir = Join-Path $updateDir "new"
$backupDir = Join-Path $updateDir "previous"
$entries = @()
foreach ($relative in $relativeFiles) {
    $staged = Join-Path $stageDir $relative
    $dest = Join-Path $Root $relative
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $staged) | Out-Null
    Invoke-WebRequest "https://raw.githubusercontent.com/$repo/$sha/$relative" -OutFile $staged -UseBasicParsing -TimeoutSec 60
    if ($relative.EndsWith(".ps1")) {
        [IO.File]::WriteAllText($staged, [IO.File]::ReadAllText($staged), [Text.UTF8Encoding]::new($true))
    } else {
        & $python -m py_compile $staged
        if ($LASTEXITCODE -ne 0) { throw "Invalid Python file: $relative" }
    }
    $existed = Test-Path -LiteralPath $dest
    $backup = Join-Path $backupDir $relative
    if ($existed) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backup) | Out-Null
        Copy-Item -LiteralPath $dest -Destination $backup
    }
    $entries += [PSCustomObject]@{Staged=$staged; Destination=$dest; Backup=$backup; Existed=$existed}
}
try {
    Stop-ScheduledTask -TaskName FirmParserExport
    Start-Sleep -Seconds 2
    Get-CimInstance Win32_Process | Where-Object {
        $_.Name -like "python*.exe" -and $_.CommandLine -and
        $_.CommandLine -match "(?:-m\s+parser\.serve_export|[\\/]serve_export\.py)"
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    foreach ($entry in $entries) {
        Copy-Item -LiteralPath $entry.Staged -Destination $entry.Destination -Force
    }
    Push-Location $Root
    try {
        & $python -c "from parser.company_checks import JobStore; from parser.export_company_checks import write_report; print('company checks imports OK')"
        if ($LASTEXITCODE -ne 0) { throw "Company checks import failed" }
    } finally { Pop-Location }
} catch {
    foreach ($entry in $entries) {
        if ($entry.Existed) { Copy-Item -LiteralPath $entry.Backup -Destination $entry.Destination -Force }
        elseif (Test-Path -LiteralPath $entry.Destination -PathType Leaf) { Remove-Item -LiteralPath $entry.Destination -Force }
    }
    throw
} finally {
    Start-ScheduledTask -TaskName FirmParserExport
}
Write-Host "OK: company checks updated from GitHub commit $sha"
Write-Host "Task settings preserved. Small code backup: $backupDir"
