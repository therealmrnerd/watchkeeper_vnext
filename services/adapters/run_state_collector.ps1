$root = Resolve-Path (Join-Path $PSScriptRoot "..\..\")
Set-Location $root
python services/adapters/state_collector.py
