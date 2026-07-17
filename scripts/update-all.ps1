#Requires -Version 5.1
<#
.SYNOPSIS
  Tiny PDF Editor - update git/npm/Python deps, optionally rebuild MSI.

.PARAMETER SkipGit
  Skip git pull.

.PARAMETER SkipNpm
  Skip npm install/update.

.PARAMETER SkipPython
  Skip Python pip upgrades.

.PARAMETER SkipCores
  Accepted for NAS4USB bat compatibility (no-op).

.PARAMETER BuildDist
  Run npm run build:dist:msi after updates.

.PARAMETER Force
  npm install --force and clear PyInstaller/.cache folders.
#>
param(
    [switch]$SkipGit,
    [switch]$SkipNpm,
    [switch]$SkipPython,
    [switch]$SkipCores,
    [switch]$BuildDist,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root '.cache\logs'
$LogFile = Join-Path $LogDir 'update-all.log'

function Write-UpdateLog {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host $line
}

$nodeArgs = @('scripts/update-all.mjs')
if ($SkipGit) { $nodeArgs += '--skip-git' }
if ($SkipNpm) { $nodeArgs += '--skip-npm' }
if ($SkipPython) { $nodeArgs += '--skip-python' }
if ($SkipCores) { $nodeArgs += '--skip-cores' }
if ($BuildDist) { $nodeArgs += '--build' }
if ($Force) { $nodeArgs += '--force' }

Write-UpdateLog '===== update-all started ====='
Write-UpdateLog "Project root: $Root"
Write-UpdateLog "Log file: $LogFile"

Push-Location $Root
try {
    & node @nodeArgs
    if ($LASTEXITCODE -ne 0) {
        throw "update-all.mjs failed (exit $LASTEXITCODE)"
    }
} finally {
    Pop-Location
}

Write-UpdateLog '===== update-all finished ====='
Write-Host ''
Write-Host '[OK] Update complete. Log:' $LogFile
