$root = Resolve-Path (Join-Path $PSScriptRoot "..\..\")
Set-Location $root
. (Join-Path $root "scripts\set_runtime_env.ps1") -InitDb -Quiet
python services/brainstem/supervisor.py
