param([string]$Target = "C:\firmy")
$ErrorActionPreference = "Stop"
$targetPath = [IO.Path]::GetFullPath($Target).TrimEnd('\')
if (-not (Test-Path -LiteralPath (Join-Path $targetPath "run_parser.py"))) {
    throw "Target must be the existing parser directory with run_parser.py"
}
$packageRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$manifest = Join-Path $packageRoot "parser-files.txt"
if (-not (Test-Path -LiteralPath $manifest)) {
    throw "Run this installer from the extracted company-checks package"
}
$packageFiles = @()
foreach ($relative in Get-Content -LiteralPath $manifest) {
    if (-not $relative.Trim()) { continue }
    $dest = [IO.Path]::GetFullPath((Join-Path $targetPath $relative))
    if (-not $dest.StartsWith($targetPath + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Invalid manifest path" }
    $source = Join-Path $packageRoot $relative
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Missing package file: $relative" }
    $packageFiles += [PSCustomObject]@{Relative=$relative; Source=$source; Destination=$dest; Existed=(Test-Path -LiteralPath $dest)}
}
$backupDir = Join-Path $targetPath ("data\code_backups\checks_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
foreach ($entry in $packageFiles) {
    if ($entry.Existed) {
        $backup = Join-Path $backupDir $entry.Relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backup) | Out-Null
        Copy-Item -LiteralPath $entry.Destination -Destination $backup
    }
}
$task = Get-ScheduledTask -TaskName FirmParserExport -ErrorAction Stop
Stop-ScheduledTask -TaskName FirmParserExport
Start-Sleep -Seconds 2
# Stop only the export service, never the scheduled Telegram parser.
Get-CimInstance Win32_Process | Where-Object {
    $_.Name -like "python*.exe" -and $_.CommandLine -and
    $_.CommandLine -match "(?:-m\s+parser\.serve_export|[\\/]serve_export\.py)"
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
try {
    foreach ($entry in $packageFiles) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $entry.Destination) | Out-Null
        Copy-Item -LiteralPath $entry.Source -Destination $entry.Destination -Force
    }
    $python = Join-Path $targetPath ".venv\Scripts\python.exe"
    & $python -c "from parser.company_checks import JobStore; from parser.export_company_checks import write_report; print('company checks imports OK')"
    if ($LASTEXITCODE -ne 0) { throw "Import check failed" }
} catch {
    foreach ($entry in $packageFiles) {
        if ($entry.Existed) {
            Copy-Item -LiteralPath (Join-Path $backupDir $entry.Relative) -Destination $entry.Destination -Force
        } elseif (Test-Path -LiteralPath $entry.Destination -PathType Leaf) {
            Remove-Item -LiteralPath $entry.Destination -Force
        }
    }
    throw
} finally {
    Start-ScheduledTask -TaskName FirmParserExport
}
Write-Host "Updated company checks. Existing task principal, triggers and credentials preserved."
Write-Host "CRM: set LAVOK_PARSER_CHECKS_URL to http://PARSER_HOST:8788/lavok/checks"
