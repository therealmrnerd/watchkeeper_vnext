$root = Resolve-Path (Join-Path $PSScriptRoot "..\..\")
Set-Location $root
. (Join-Path $root "scripts\set_runtime_env.ps1") -Quiet -InitDb:$false
python services/adapters/edparser_vnext.py
