$root = Resolve-Path (Join-Path $PSScriptRoot "..\..\")
Set-Location $root
python services/ai/knowledge_service.py
