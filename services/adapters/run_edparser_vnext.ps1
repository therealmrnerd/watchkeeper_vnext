$root = Resolve-Path (Join-Path $PSScriptRoot "..\..\")
Set-Location $root
python services/adapters/edparser_vnext.py
