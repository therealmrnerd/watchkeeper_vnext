param(
  [switch]$InitDb = $true,
  [switch]$Quiet = $false
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$dataDir = Join-Path $root "data"
$nowPlayingDir = Join-Path $dataDir "now-playing"
$storageDir = Join-Path $root "storage"

foreach ($path in @($dataDir, $nowPlayingDir, $storageDir)) {
  if (-not (Test-Path $path)) {
    New-Item -ItemType Directory -Path $path -Force | Out-Null
  }
}

function Set-EnvDefault {
  param(
    [string]$Name,
    [string]$Value
  )
  $current = [Environment]::GetEnvironmentVariable($Name, "Process")
  if ([string]::IsNullOrWhiteSpace($current)) {
    [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
  }
}

function Resolve-PreferredPath {
  param(
    [string[]]$Candidates
  )
  foreach ($candidate in $Candidates) {
    if ([string]::IsNullOrWhiteSpace($candidate)) {
      continue
    }
    if (Test-Path $candidate) {
      return (Resolve-Path $candidate).Path
    }
  }
  return $Candidates[0]
}

$dbPath = Join-Path $dataDir "watchkeeper_vnext.db"
$schemaDir = Join-Path $root "schemas\sqlite"
$schemaPath = Join-Path $schemaDir "001_brainstem_core.sql"
$edTelemetryPath = Join-Path $dataDir "ed_telemetry.json"
$hardwareProbePath = Join-Path $dataDir "hardware_probe.json"
$qdrantPidPath = Join-Path $dataDir "qdrant_runtime.pid.json"

Set-EnvDefault -Name "WKV_DB_PATH" -Value $dbPath
Set-EnvDefault -Name "WKV_AI_DB_PATH" -Value $dbPath
Set-EnvDefault -Name "WKV_SCHEMA_PATH" -Value $schemaPath
Set-EnvDefault -Name "WKV_SCHEMA_DIR" -Value $schemaDir
Set-EnvDefault -Name "WKV_NOW_PLAYING_DIR" -Value $nowPlayingDir
Set-EnvDefault -Name "WKV_ED_TELEMETRY_JSON" -Value $edTelemetryPath
Set-EnvDefault -Name "WKV_ED_TELEMETRY_OUT" -Value $edTelemetryPath
Set-EnvDefault -Name "WKV_HARDWAREPROBE_JSON" -Value $hardwareProbePath
Set-EnvDefault -Name "WKV_QDRANT_PID_FILE" -Value $qdrantPidPath

$qdrantBin = Resolve-PreferredPath -Candidates @(
  (Join-Path $root "tools\qdrant\qdrant.exe"),
  "C:\ai\tools\qdrant\qdrant.exe"
)
Set-EnvDefault -Name "WKV_QDRANT_BIN" -Value $qdrantBin
Set-EnvDefault -Name "WKV_QDRANT_WORKDIR" -Value (Split-Path -Parent $qdrantBin)

$phi3ModelPath = Resolve-PreferredPath -Candidates @(
  (Join-Path $root "models\llm\phi3-mini-4k-int4-ov"),
  (Join-Path $root "models\llm\qwen2.5-7b-instruct-ov-8bit")
)
$whisperModelPath = Resolve-PreferredPath -Candidates @(
  (Join-Path $root "models\speech\whisper-base-int4-ov"),
  (Join-Path $root "models\stt\distil-whisper-distil-small-en")
)
$ttsModelPath = Resolve-PreferredPath -Candidates @(
  (Join-Path $root "models\tts\bender_piper\en_US-bender-medium.onnx"),
  (Join-Path $root "models\tts\wheatley1\wheatley1.onnx"),
  (Join-Path $root "models\tts\Patrick\en_US-patrick-medium.onnx")
)
$voskPath = Join-Path $root "models\stt\vosk-model-small-en-us-0.15"

Set-EnvDefault -Name "WK_PHI3_DIR" -Value $phi3ModelPath
Set-EnvDefault -Name "WHISPER_MODEL_DIR" -Value $whisperModelPath
Set-EnvDefault -Name "WK_TTS_MODEL" -Value $ttsModelPath
if (Test-Path $voskPath) {
  Set-EnvDefault -Name "WK_VOSK_MODEL" -Value (Resolve-Path $voskPath).Path
}

Set-EnvDefault -Name "AI_DATA_DIR" -Value $dataDir
Set-EnvDefault -Name "MEMORY_DB_PATH" -Value (Join-Path $dataDir "memory.db")
Set-EnvDefault -Name "STATE_DB_PATH" -Value (Join-Path $dataDir "memory.db")

if ($InitDb) {
  $effectiveDbPath = [Environment]::GetEnvironmentVariable("WKV_DB_PATH", "Process")
  if (-not (Test-Path $effectiveDbPath)) {
    & (Join-Path $root "scripts\create_db.ps1") -DbPath $effectiveDbPath | Out-Null
  }
}

if (-not $Quiet) {
  Write-Host "Watchkeeper runtime environment configured:"
  Write-Host "  WKV_DB_PATH=$([Environment]::GetEnvironmentVariable('WKV_DB_PATH','Process'))"
  Write-Host "  WKV_AI_DB_PATH=$([Environment]::GetEnvironmentVariable('WKV_AI_DB_PATH','Process'))"
  Write-Host "  WKV_NOW_PLAYING_DIR=$([Environment]::GetEnvironmentVariable('WKV_NOW_PLAYING_DIR','Process'))"
  Write-Host "  WK_PHI3_DIR=$([Environment]::GetEnvironmentVariable('WK_PHI3_DIR','Process'))"
  Write-Host "  WHISPER_MODEL_DIR=$([Environment]::GetEnvironmentVariable('WHISPER_MODEL_DIR','Process'))"
  Write-Host "  WK_TTS_MODEL=$([Environment]::GetEnvironmentVariable('WK_TTS_MODEL','Process'))"
  Write-Host "  WKV_QDRANT_BIN=$([Environment]::GetEnvironmentVariable('WKV_QDRANT_BIN','Process'))"
}
