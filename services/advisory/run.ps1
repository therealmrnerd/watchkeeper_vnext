$root = Resolve-Path (Join-Path $PSScriptRoot "..\..\")
Set-Location $root
. (Join-Path $root "scripts\set_runtime_env.ps1") -InitDb -Quiet
$pythonExe = [Environment]::GetEnvironmentVariable("WKV_ADVISORY_PYTHON", "Process")
if ([string]::IsNullOrWhiteSpace($pythonExe)) {
  $pythonExe = "python"
}
& $pythonExe services/advisory/app.py
