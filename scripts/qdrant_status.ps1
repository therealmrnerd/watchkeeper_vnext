$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root
python services/ai/qdrant_runtime.py status
