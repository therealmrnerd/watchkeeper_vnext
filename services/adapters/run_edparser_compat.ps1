$root = Resolve-Path (Join-Path $PSScriptRoot "..\..\")
Set-Location $root
node services/adapters/edparser_compat.mjs
