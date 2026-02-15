$root = Resolve-Path (Join-Path $PSScriptRoot "..\..\")
Set-Location $root
python services/brainstem/supervisor.py
