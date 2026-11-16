#Requires -Version 5.1
<#
.SYNOPSIS
  Tiny PDF Editor - NEO - npm·Python 의존성과 Electron 을 최신으로 업데이트하고, 필요하면 릴리스 빌드까지 실행합니다.

.PARAMETER SkipGit
  git pull 을 건너뜁니다.

.PARAMETER SkipNpm
  npm install/update 와 Electron 최신화를 건너뜁니다.

.PARAMETER SkipPython
  Python 엔진 패키지 최신화(pip, requirements.txt 갱신)를 건너뜁니다.

.PARAMETER SkipMajors
  package.json 범위를 유지하고 Electron / electron-builder 만 최신으로 올립니다.

.PARAMETER BuildDist
  업데이트 후 npm run build:release 를 실행합니다.
#>
param(
    [switch]$SkipGit,
    [switch]$SkipNpm,
    [switch]$SkipPython,
    [switch]$SkipMajors,
    [switch]$BuildDist
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
if ($SkipMajors) { $nodeArgs += '--skip-majors' }
if ($BuildDist) { $nodeArgs += '--build' }

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
