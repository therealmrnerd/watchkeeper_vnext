$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root
. (Join-Path $root "scripts\set_runtime_env.ps1") -Quiet -InitDb:$false
python services/ai/qdrant_runtime.py stop
