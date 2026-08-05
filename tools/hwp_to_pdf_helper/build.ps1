$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$root = (Resolve-Path (Join-Path $here "..\..")).Path
$outDir = Join-Path $root "pdf_editor\vendor"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) {
  throw "32-bit csc.exe not found: $csc"
}
$exe = Join-Path $outDir "hwp_to_pdf_helper.exe"
& $csc /nologo /optimize+ /platform:x86 /target:exe /out:$exe (Join-Path $here "Program.cs")
if ($LASTEXITCODE -ne 0) { throw "csc failed: $LASTEXITCODE" }
Write-Output "built $exe"
