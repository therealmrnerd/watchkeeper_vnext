param(
  [ValidateSet("start", "stop", "status", "restart")]
  [string]$Action = "start",
  [int]$HealthTimeoutSec = 45,
  [switch]$NoHealthChecks
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

. (Join-Path $root "scripts\set_runtime_env.ps1") -Quiet -InitDb

$dataDir = Join-Path $root "data"
if (-not (Test-Path $dataDir)) {
  New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
}
$stateFile = Join-Path $dataDir "stack_processes.json"

$services = @(
  [pscustomobject]@{
    Name = "brainstem"
    Script = "services/brainstem/run.ps1"
    Kind = "http"
    HealthUrl = "http://127.0.0.1:8787/health"
  },
  [pscustomobject]@{
    Name = "knowledge"
    Script = "services/ai/run_knowledge.ps1"
    Kind = "http"
    HealthUrl = "http://127.0.0.1:8790/health"
  },
  [pscustomobject]@{
    Name = "assist_router"
    Script = "services/ai/run_assist_router.ps1"
    Kind = "http"
    HealthUrl = "http://127.0.0.1:8791/health"
  },
  [pscustomobject]@{
    Name = "supervisor"
    Script = "services/brainstem/run_supervisor.ps1"
    Kind = "process"
    HealthUrl = $null
  },
  [pscustomobject]@{
    Name = "state_collector"
    Script = "services/adapters/run_state_collector.ps1"
    Kind = "process"
    HealthUrl = $null
  }
)

function UtcNowIso {
  return (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
}

function Test-PidRunning {
  param([int]$ProcessId)
  if ($ProcessId -le 0) {
    return $false
  }
  try {
    $p = Get-Process -Id $ProcessId -ErrorAction Stop
    return -not $p.HasExited
  } catch {
    return $false
  }
}

function Test-HealthEndpoint {
  param(
    [string]$Url,
    [int]$TimeoutSec = 3
  )
  if ([string]::IsNullOrWhiteSpace($Url)) {
    return $false
  }
  try {
    $resp = Invoke-RestMethod -Method Get -Uri $Url -TimeoutSec $TimeoutSec
    return [bool]($resp -and $resp.ok -eq $true)
  } catch {
    return $false
  }
}

function Read-StackState {
  if (-not (Test-Path $stateFile)) {
    return @{}
  }
  try {
    $raw = Get-Content -Path $stateFile -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($raw)) {
      return @{}
    }
    $json = $raw | ConvertFrom-Json
    $table = @{}
    if ($json.services) {
      foreach ($svc in $json.services) {
        $table[$svc.name] = $svc
      }
    }
    return $table
  } catch {
    Write-Warning "Failed to parse state file: $stateFile"
    return @{}
  }
}

function Write-StackState {
  param([hashtable]$StateTable)

  $rows = @()
  foreach ($name in $StateTable.Keys) {
    $rows += [pscustomobject]@{
      name = $name
      pid = [int]$StateTable[$name].pid
      script = [string]$StateTable[$name].script
      started_at_utc = [string]$StateTable[$name].started_at_utc
      managed = $true
    }
  }
  $doc = [pscustomobject]@{
    root = $root
    updated_at_utc = UtcNowIso
    services = ($rows | Sort-Object name)
  }
  $doc | ConvertTo-Json -Depth 6 | Set-Content -Path $stateFile -Encoding UTF8
}

function Remove-StackStateIfEmpty {
  param([hashtable]$StateTable)
  if ($StateTable.Count -eq 0) {
    Remove-Item -Path $stateFile -Force -ErrorAction SilentlyContinue
  }
}

function Start-ServiceProcess {
  param(
    [pscustomobject]$Service,
    [hashtable]$StateTable,
    [System.Collections.ArrayList]$StartedThisRun
  )

  $existing = $StateTable[$Service.Name]
  if ($existing -and (Test-PidRunning -ProcessId ([int]$existing.pid))) {
    Write-Host ("[skip] {0} already running (pid={1})" -f $Service.Name, $existing.pid)
    return
  }

  if ($Service.Kind -eq "http" -and (Test-HealthEndpoint -Url $Service.HealthUrl -TimeoutSec 2)) {
    Write-Host ("[skip] {0} health endpoint already up (external process)" -f $Service.Name)
    return
  }

  $scriptPath = Join-Path $root $Service.Script
  if (-not (Test-Path $scriptPath)) {
    throw "Missing startup script for $($Service.Name): $scriptPath"
  }

  $proc = Start-Process `
    -FilePath "powershell" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $scriptPath) `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -PassThru

  $StateTable[$Service.Name] = [pscustomobject]@{
    pid = [int]$proc.Id
    script = $Service.Script
    started_at_utc = UtcNowIso
  }
  [void]$StartedThisRun.Add($Service.Name)
  Write-Host ("[start] {0} pid={1}" -f $Service.Name, $proc.Id)
}

function Stop-ServiceProcess {
  param(
    [pscustomobject]$Service,
    [hashtable]$StateTable
  )

  $existing = $StateTable[$Service.Name]
  if (-not $existing) {
    Write-Host ("[skip] {0} not managed by stack state" -f $Service.Name)
    return
  }

  $procId = [int]$existing.pid
  if (-not (Test-PidRunning -ProcessId $procId)) {
    Write-Host ("[stale] {0} pid={1} not running" -f $Service.Name, $procId)
    $StateTable.Remove($Service.Name)
    return
  }

  try {
    taskkill /PID $procId /T /F | Out-Null
  } catch {
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
  }
  Start-Sleep -Milliseconds 250
  if (Test-PidRunning -ProcessId $procId) {
    Write-Warning ("[warn] failed to stop {0} pid={1}" -f $Service.Name, $procId)
  } else {
    Write-Host ("[stop] {0} pid={1}" -f $Service.Name, $procId)
    $StateTable.Remove($Service.Name)
  }
}

function Wait-ForServiceHealthy {
  param(
    [pscustomobject]$Service,
    [hashtable]$StateTable,
    [int]$TimeoutSec
  )
  $deadline = (Get-Date).AddSeconds([Math]::Max(1, $TimeoutSec))
  while ((Get-Date) -lt $deadline) {
    $entry = $StateTable[$Service.Name]
    if ($entry) {
      $procId = [int]$entry.pid
      if (-not (Test-PidRunning -ProcessId $procId)) {
        throw "$($Service.Name) exited before healthy check completed (pid=$procId)"
      }
    }

    if ($Service.Kind -eq "process") {
      if ($entry -and (Test-PidRunning -ProcessId ([int]$entry.pid))) {
        return
      }
    } else {
      if (Test-HealthEndpoint -Url $Service.HealthUrl -TimeoutSec 2) {
        return
      }
    }
    Start-Sleep -Milliseconds 500
  }

  if ($Service.Kind -eq "http") {
    throw "Health check timeout for $($Service.Name) at $($Service.HealthUrl)"
  }
  throw "Process health timeout for $($Service.Name)"
}

function Show-Status {
  param([hashtable]$StateTable)
  Write-Host ("Stack status at {0}" -f (UtcNowIso))
  foreach ($svc in $services) {
    $entry = $StateTable[$svc.Name]
    $managed = $false
    $procId = $null
    $running = $false
    if ($entry) {
      $managed = $true
      $procId = [int]$entry.pid
      $running = Test-PidRunning -ProcessId $procId
    }
    $health = $null
    if ($svc.Kind -eq "http") {
      $health = Test-HealthEndpoint -Url $svc.HealthUrl -TimeoutSec 2
      Write-Host (" - {0}: managed={1} pid={2} running={3} health={4}" -f $svc.Name, $managed, $procId, $running, $health)
    } else {
      Write-Host (" - {0}: managed={1} pid={2} running={3}" -f $svc.Name, $managed, $procId, $running)
    }
  }
}

function Get-ReverseServices {
  $copy = @($services)
  [array]::Reverse($copy)
  return $copy
}

function Start-Stack {
  $state = Read-StackState
  $started = New-Object System.Collections.ArrayList
  try {
    foreach ($svc in $services) {
      Start-ServiceProcess -Service $svc -StateTable $state -StartedThisRun $started
    }
    Write-StackState -StateTable $state

    if (-not $NoHealthChecks) {
      foreach ($svc in $services) {
        Wait-ForServiceHealthy -Service $svc -StateTable $state -TimeoutSec $HealthTimeoutSec
      }
    }
    Write-Host "Stack start complete."
    Show-Status -StateTable $state
  } catch {
    Write-Warning ("Stack start failed: {0}" -f $_.Exception.Message)
    if ($started.Count -gt 0) {
      Write-Host "Stopping services started in this run..."
      $reverse = Get-ReverseServices
      foreach ($svc in $reverse) {
        if ($started -contains $svc.Name) {
          Stop-ServiceProcess -Service $svc -StateTable $state
        }
      }
      Write-StackState -StateTable $state
      Remove-StackStateIfEmpty -StateTable $state
    }
    throw
  }
}

function Stop-Stack {
  $state = Read-StackState
  $reverse = Get-ReverseServices
  foreach ($svc in $reverse) {
    Stop-ServiceProcess -Service $svc -StateTable $state
  }
  if ($state.Count -gt 0) {
    Write-StackState -StateTable $state
  } else {
    Remove-StackStateIfEmpty -StateTable $state
  }
  Write-Host "Stack stop complete."
  Show-Status -StateTable $state
}

switch ($Action) {
  "start" {
    Start-Stack
  }
  "stop" {
    Stop-Stack
  }
  "restart" {
    Stop-Stack
    Start-Stack
  }
  "status" {
    $state = Read-StackState
    Show-Status -StateTable $state
  }
  default {
    throw "Unsupported action: $Action"
  }
}
