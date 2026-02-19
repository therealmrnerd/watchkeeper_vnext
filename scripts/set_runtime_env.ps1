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
$statsDir = Resolve-PreferredPath -Candidates @(
  "C:\ai\Watchkeeper\stats",
  (Join-Path $root "stats")
)
$qdrantPidPath = Join-Path $dataDir "qdrant_runtime.pid.json"
$userProfile = [Environment]::GetFolderPath("UserProfile")

Set-EnvDefault -Name "WKV_DB_PATH" -Value $dbPath
Set-EnvDefault -Name "WKV_AI_DB_PATH" -Value $dbPath
Set-EnvDefault -Name "WKV_SCHEMA_PATH" -Value $schemaPath
Set-EnvDefault -Name "WKV_SCHEMA_DIR" -Value $schemaDir
Set-EnvDefault -Name "WKV_NOW_PLAYING_DIR" -Value $nowPlayingDir
if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable("WKV_LEGACY_NOW_PLAYING_DIR", "Process"))) {
  [Environment]::SetEnvironmentVariable("WKV_NOW_PLAYING_FALLBACK_DIR", $null, "Process")
} elseif (Test-Path ([Environment]::GetEnvironmentVariable("WKV_LEGACY_NOW_PLAYING_DIR", "Process"))) {
  Set-EnvDefault -Name "WKV_NOW_PLAYING_FALLBACK_DIR" -Value ([Environment]::GetEnvironmentVariable("WKV_LEGACY_NOW_PLAYING_DIR", "Process"))
}
Set-EnvDefault -Name "WKV_ED_TELEMETRY_JSON" -Value $edTelemetryPath
Set-EnvDefault -Name "WKV_ED_TELEMETRY_OUT" -Value $edTelemetryPath
Set-EnvDefault -Name "WKV_HARDWAREPROBE_JSON" -Value $hardwareProbePath
Set-EnvDefault -Name "WKV_SUP_STATS_TXT_ENABLED" -Value "1"
Set-EnvDefault -Name "WKV_SUP_STATS_DIR" -Value $statsDir
Set-EnvDefault -Name "WKV_SUP_STATS_LINE_SEC" -Value "10"
Set-EnvDefault -Name "WKV_QDRANT_PID_FILE" -Value $qdrantPidPath
Set-EnvDefault -Name "WKV_SUP_AUX_APPS_AUTORUN" -Value "1"

$sammiExe = Resolve-PreferredPath -Candidates @(
  (Join-Path $userProfile "Desktop\SAMMI.2022.4.3-x64\x64\SAMMI Core.exe"),
  "C:\ai\Watchkeeper\Sammi\SAMMI Core.exe"
)
$jinxExe = Resolve-PreferredPath -Candidates @(
  (Join-Path $userProfile "Documents\Hi-Jinx\Hi-Jinx.exe"),
  (Join-Path $userProfile "Documents\Hi-Jinx 2\Hi-Jinx 2.exe")
)
$jinxSenderPath = Resolve-PreferredPath -Candidates @(
  (Join-Path $root "tools\jinxsender.py"),
  "C:\ai\Watchkeeper\Tools\jinxsender.py"
)
$jinxEnvMapPath = Resolve-PreferredPath -Candidates @(
  (Join-Path $root "config\jinx_envmap.json"),
  "C:\ai\Watchkeeper\Tools\jinx_envmap.json"
)
$edAhkPath = Resolve-PreferredPath -Candidates @(
  (Join-Path $userProfile "Desktop\Watchkeeper\Tools\ED.ahk"),
  (Join-Path $userProfile "Desktop\ED.ahk"),
  "C:\ai\Watchkeeper\Tools\ED.ahk"
)
$ahkExe = Resolve-PreferredPath -Candidates @(
  "C:\Program Files\AutoHotkey\AutoHotkey64.exe",
  "C:\Program Files\AutoHotkey\AutoHotkey.exe",
  "C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe",
  "C:\Program Files\AutoHotkey\v2\AutoHotkey.exe"
)
Set-EnvDefault -Name "WKV_SUP_SAMMI_EXE" -Value $sammiExe
Set-EnvDefault -Name "WKV_SUP_JINX_EXE" -Value $jinxExe
Set-EnvDefault -Name "WKV_SUP_JINX_ARGS" -Value "-m"
Set-EnvDefault -Name "WKV_SUP_JINX_SYNC_ENABLED" -Value "1"
Set-EnvDefault -Name "WKV_SUP_JINX_SYNC_VAR" -Value "sync"
Set-EnvDefault -Name "WKV_SUP_JINX_PYTHON" -Value "python"
Set-EnvDefault -Name "WKV_SUP_JINX_SENDER_PATH" -Value $jinxSenderPath
Set-EnvDefault -Name "WKV_SUP_JINX_ENV_MAP_PATH" -Value $jinxEnvMapPath
Set-EnvDefault -Name "WKV_SUP_JINX_ARTNET_IP" -Value "127.0.0.1"
Set-EnvDefault -Name "WKV_SUP_JINX_ARTNET_UNIVERSE" -Value "1"
Set-EnvDefault -Name "WKV_SUP_JINX_BRIGHTNESS" -Value "200"
Set-EnvDefault -Name "WKV_SUP_JINX_OFF_EFFECT" -Value "S1"
Set-EnvDefault -Name "WKV_SUP_ED_AHK_PATH" -Value $edAhkPath
Set-EnvDefault -Name "WKV_SUP_AHK_EXE" -Value $ahkExe
Set-EnvDefault -Name "WKV_SUP_ED_AHK_STOP_ON_ED_EXIT" -Value "1"
Set-EnvDefault -Name "WKV_SUP_ED_AHK_RESTART_BACKOFF_SEC" -Value "3"
Set-EnvDefault -Name "WKV_SUP_AHK_PROTECTED_SCRIPTS" -Value "stack_tray.ahk"
Set-EnvDefault -Name "WKV_SAMMI_API_ENABLED" -Value "1"
Set-EnvDefault -Name "WKV_SAMMI_API_HOST" -Value "127.0.0.1"
Set-EnvDefault -Name "WKV_SAMMI_API_PORT" -Value "9450"
Set-EnvDefault -Name "WKV_SAMMI_API_TIMEOUT_SEC" -Value "0.6"
Set-EnvDefault -Name "WKV_SAMMI_API_MAX_UPDATES_PER_CYCLE" -Value "12"
Set-EnvDefault -Name "WKV_SAMMI_API_ONLY_WHEN_ED" -Value "1"
Set-EnvDefault -Name "WKV_SAMMI_NEW_WRITE_VAR" -Value "ID116.new_write"
Set-EnvDefault -Name "WKV_SAMMI_NEW_WRITE_COMPAT_VAR" -Value "ID116.new_write"
Set-EnvDefault -Name "WKV_SAMMI_NEW_WRITE_IGNORE_VARS" -Value "Heartbeat,timestamp"
Set-EnvDefault -Name "WKV_SUP_ED_ACTIVE_SEC" -Value "0.35"
Set-EnvDefault -Name "WKV_SUP_LOOP_SLEEP_SEC" -Value "0.1"
Set-EnvDefault -Name "WKV_EDPARSER_ACTIVE_SEC" -Value "0.35"
Set-EnvDefault -Name "WKV_SUP_HARDWARE_REQUIRES_JINX" -Value "1"
Set-EnvDefault -Name "WKV_SUP_MUSIC_REQUIRES_PROCESS" -Value "1"
Set-EnvDefault -Name "WKV_SUP_MUSIC_PROCESS_NAMES" -Value "YouTube Music Desktop App.exe,YouTubeMusicDesktopApp.exe,YouTube Music.exe,ytmdesktop.exe"
Set-EnvDefault -Name "WKV_YTMD_PROCESS_NAMES" -Value "YouTube Music Desktop App.exe,YouTubeMusicDesktopApp.exe,YouTube Music.exe,ytmdesktop.exe"

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
  Write-Host "  WKV_NOW_PLAYING_FALLBACK_DIR=$([Environment]::GetEnvironmentVariable('WKV_NOW_PLAYING_FALLBACK_DIR','Process'))"
  Write-Host "  WK_PHI3_DIR=$([Environment]::GetEnvironmentVariable('WK_PHI3_DIR','Process'))"
  Write-Host "  WHISPER_MODEL_DIR=$([Environment]::GetEnvironmentVariable('WHISPER_MODEL_DIR','Process'))"
  Write-Host "  WK_TTS_MODEL=$([Environment]::GetEnvironmentVariable('WK_TTS_MODEL','Process'))"
  Write-Host "  WKV_QDRANT_BIN=$([Environment]::GetEnvironmentVariable('WKV_QDRANT_BIN','Process'))"
  Write-Host "  WKV_SUP_AUX_APPS_AUTORUN=$([Environment]::GetEnvironmentVariable('WKV_SUP_AUX_APPS_AUTORUN','Process'))"
  Write-Host "  WKV_SUP_SAMMI_EXE=$([Environment]::GetEnvironmentVariable('WKV_SUP_SAMMI_EXE','Process'))"
  Write-Host "  WKV_SUP_JINX_EXE=$([Environment]::GetEnvironmentVariable('WKV_SUP_JINX_EXE','Process'))"
  Write-Host "  WKV_SUP_JINX_ARGS=$([Environment]::GetEnvironmentVariable('WKV_SUP_JINX_ARGS','Process'))"
  Write-Host "  WKV_SUP_JINX_SYNC_ENABLED=$([Environment]::GetEnvironmentVariable('WKV_SUP_JINX_SYNC_ENABLED','Process'))"
  Write-Host "  WKV_SUP_JINX_SENDER_PATH=$([Environment]::GetEnvironmentVariable('WKV_SUP_JINX_SENDER_PATH','Process'))"
  Write-Host "  WKV_SUP_JINX_ENV_MAP_PATH=$([Environment]::GetEnvironmentVariable('WKV_SUP_JINX_ENV_MAP_PATH','Process'))"
  Write-Host "  WKV_SUP_ED_AHK_PATH=$([Environment]::GetEnvironmentVariable('WKV_SUP_ED_AHK_PATH','Process'))"
  Write-Host "  WKV_SUP_AHK_EXE=$([Environment]::GetEnvironmentVariable('WKV_SUP_AHK_EXE','Process'))"
  Write-Host "  WKV_SUP_ED_AHK_STOP_ON_ED_EXIT=$([Environment]::GetEnvironmentVariable('WKV_SUP_ED_AHK_STOP_ON_ED_EXIT','Process'))"
  Write-Host "  WKV_SUP_ED_AHK_RESTART_BACKOFF_SEC=$([Environment]::GetEnvironmentVariable('WKV_SUP_ED_AHK_RESTART_BACKOFF_SEC','Process'))"
  Write-Host "  WKV_SUP_AHK_PROTECTED_SCRIPTS=$([Environment]::GetEnvironmentVariable('WKV_SUP_AHK_PROTECTED_SCRIPTS','Process'))"
  Write-Host "  WKV_SAMMI_API_ENABLED=$([Environment]::GetEnvironmentVariable('WKV_SAMMI_API_ENABLED','Process'))"
  Write-Host "  WKV_SAMMI_API_HOST=$([Environment]::GetEnvironmentVariable('WKV_SAMMI_API_HOST','Process'))"
  Write-Host "  WKV_SAMMI_API_PORT=$([Environment]::GetEnvironmentVariable('WKV_SAMMI_API_PORT','Process'))"
  Write-Host "  WKV_SAMMI_API_TIMEOUT_SEC=$([Environment]::GetEnvironmentVariable('WKV_SAMMI_API_TIMEOUT_SEC','Process'))"
  Write-Host "  WKV_SAMMI_API_MAX_UPDATES_PER_CYCLE=$([Environment]::GetEnvironmentVariable('WKV_SAMMI_API_MAX_UPDATES_PER_CYCLE','Process'))"
  Write-Host "  WKV_SAMMI_API_ONLY_WHEN_ED=$([Environment]::GetEnvironmentVariable('WKV_SAMMI_API_ONLY_WHEN_ED','Process'))"
  Write-Host "  WKV_SAMMI_NEW_WRITE_VAR=$([Environment]::GetEnvironmentVariable('WKV_SAMMI_NEW_WRITE_VAR','Process'))"
  Write-Host "  WKV_SAMMI_NEW_WRITE_COMPAT_VAR=$([Environment]::GetEnvironmentVariable('WKV_SAMMI_NEW_WRITE_COMPAT_VAR','Process'))"
  Write-Host "  WKV_SAMMI_NEW_WRITE_IGNORE_VARS=$([Environment]::GetEnvironmentVariable('WKV_SAMMI_NEW_WRITE_IGNORE_VARS','Process'))"
  Write-Host "  WKV_SUP_ED_ACTIVE_SEC=$([Environment]::GetEnvironmentVariable('WKV_SUP_ED_ACTIVE_SEC','Process'))"
  Write-Host "  WKV_SUP_LOOP_SLEEP_SEC=$([Environment]::GetEnvironmentVariable('WKV_SUP_LOOP_SLEEP_SEC','Process'))"
  Write-Host "  WKV_EDPARSER_ACTIVE_SEC=$([Environment]::GetEnvironmentVariable('WKV_EDPARSER_ACTIVE_SEC','Process'))"
  Write-Host "  WKV_SUP_HARDWARE_REQUIRES_JINX=$([Environment]::GetEnvironmentVariable('WKV_SUP_HARDWARE_REQUIRES_JINX','Process'))"
  Write-Host "  WKV_SUP_MUSIC_REQUIRES_PROCESS=$([Environment]::GetEnvironmentVariable('WKV_SUP_MUSIC_REQUIRES_PROCESS','Process'))"
  Write-Host "  WKV_SUP_MUSIC_PROCESS_NAMES=$([Environment]::GetEnvironmentVariable('WKV_SUP_MUSIC_PROCESS_NAMES','Process'))"
  Write-Host "  WKV_YTMD_PROCESS_NAMES=$([Environment]::GetEnvironmentVariable('WKV_YTMD_PROCESS_NAMES','Process'))"
  Write-Host "  WKV_SUP_STATS_TXT_ENABLED=$([Environment]::GetEnvironmentVariable('WKV_SUP_STATS_TXT_ENABLED','Process'))"
  Write-Host "  WKV_SUP_STATS_DIR=$([Environment]::GetEnvironmentVariable('WKV_SUP_STATS_DIR','Process'))"
  Write-Host "  WKV_SUP_STATS_LINE_SEC=$([Environment]::GetEnvironmentVariable('WKV_SUP_STATS_LINE_SEC','Process'))"
}
