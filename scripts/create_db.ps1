param(
  [string]$DbPath = "data/watchkeeper_vnext.db",
  [string]$SchemaPath = "schemas/sqlite/001_brainstem_core.sql"
)

if (-not (Test-Path $SchemaPath)) {
  Write-Error "Schema file not found: $SchemaPath"
  exit 1
}

$dbDir = Split-Path -Parent $DbPath
if ($dbDir -and -not (Test-Path $dbDir)) {
  New-Item -ItemType Directory -Path $dbDir -Force | Out-Null
}

$sqliteCmd = Get-Command sqlite3 -ErrorAction SilentlyContinue
if ($sqliteCmd) {
  sqlite3 $DbPath ".read $SchemaPath"
  if ($LASTEXITCODE -ne 0) {
    Write-Error "sqlite3 failed applying schema."
    exit 1
  }
  Write-Host "Database initialized at $DbPath (via sqlite3.exe)"
  exit 0
}

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
  Write-Error "Neither sqlite3 nor python was found in PATH. Install one and rerun."
  exit 1
}

$schemaSql = Get-Content -Raw $SchemaPath
$py = @"
import sqlite3
from pathlib import Path

db_path = Path(r'''$DbPath''')
schema_sql = r'''$schemaSql'''
db_path.parent.mkdir(parents=True, exist_ok=True)
con = sqlite3.connect(db_path)
try:
    con.executescript(schema_sql)
    con.commit()
finally:
    con.close()
"@

$py | python -
if ($LASTEXITCODE -ne 0) {
  Write-Error "Python sqlite fallback failed applying schema."
  exit 1
}

Write-Host "Database initialized at $DbPath (via python sqlite3 fallback)"
