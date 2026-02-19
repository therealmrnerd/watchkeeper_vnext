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
$logsDir = Join-Path $root "logs"
if (-not (Test-Path $logsDir)) {
  New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
}

$services = @(
  [pscustomobject]@{
    Name = "brainstem"
    Script = "services/brainstem/run.ps1"
    MatchArgs = @("services/brainstem/run.ps1", "services/brainstem/app.py")
    Kind = "http"
    HealthUrl = "http://127.0.0.1:8787/health"
  },
  [pscustomobject]@{
    Name = "knowledge"
    Script = "services/ai/run_knowledge.ps1"
    MatchArgs = @("services/ai/run_knowledge.ps1", "services/ai/knowledge_service.py")
    Kind = "http"
    HealthUrl = "http://127.0.0.1:8790/health"
  },
  [pscustomobject]@{
    Name = "assist_router"
    Script = "services/ai/run_assist_router.ps1"
    MatchArgs = @("services/ai/run_assist_router.ps1", "services/ai/assist_router.py")
    Kind = "http"
    HealthUrl = "http://127.0.0.1:8791/health"
  },
  [pscustomobject]@{
    Name = "supervisor"
    Script = "services/brainstem/run_supervisor.ps1"
    MatchArgs = @("services/brainstem/run_supervisor.ps1", "services/brainstem/supervisor.py")
    Kind = "process"
    HealthUrl = $null
  },
  [pscustomobject]@{
    Name = "state_collector"
    Script = "services/adapters/run_state_collector.ps1"
    MatchArgs = @("services/adapters/run_state_collector.ps1", "services/adapters/state_collector.py")
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
      stdout_log = [string]$StateTable[$name].stdout_log
      stderr_log = [string]$StateTable[$name].stderr_log
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

  $externalPids = Find-ServiceProcessIds -Service $Service
  if ($externalPids.Count -gt 0) {
    $selected = [int](($externalPids | Sort-Object -Descending)[0])
    foreach ($candidatePid in $externalPids) {
      $pidValue = [int]$candidatePid
      if ($pidValue -eq $selected) {
        continue
      }
      try {
        taskkill /PID $pidValue /T /F | Out-Null
        Write-Host ("[dedupe] {0} terminated duplicate pid={1}" -f $Service.Name, $pidValue)
      } catch {
        Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
      }
    }
    $stdoutLog = Join-Path $logsDir ("{0}.out.log" -f $Service.Name)
    $stderrLog = Join-Path $logsDir ("{0}.err.log" -f $Service.Name)
    $StateTable[$Service.Name] = [pscustomobject]@{
      pid = $selected
      script = $Service.Script
      started_at_utc = UtcNowIso
      stdout_log = $stdoutLog
      stderr_log = $stderrLog
    }
    Write-Host ("[adopt] {0} existing pid={1}" -f $Service.Name, $selected)
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
  $stdoutLog = Join-Path $logsDir ("{0}.out.log" -f $Service.Name)
  $stderrLog = Join-Path $logsDir ("{0}.err.log" -f $Service.Name)

  $proc = Start-Process `
    -FilePath "powershell" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $scriptPath) `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

  $StateTable[$Service.Name] = [pscustomobject]@{
    pid = [int]$proc.Id
    script = $Service.Script
    started_at_utc = UtcNowIso
    stdout_log = $stdoutLog
    stderr_log = $stderrLog
  }
  [void]$StartedThisRun.Add($Service.Name)
  Write-Host ("[start] {0} pid={1}" -f $Service.Name, $proc.Id)
}

function Stop-ServiceProcess {
  param(
    [pscustomobject]$Service,
    [hashtable]$StateTable,
    [switch]$IncludeUnmanaged
  )

  $existing = $StateTable[$Service.Name]
  if ($existing) {
    $procId = [int]$existing.pid
    if (-not (Test-PidRunning -ProcessId $procId)) {
      Write-Host ("[stale] {0} pid={1} not running" -f $Service.Name, $procId)
      $StateTable.Remove($Service.Name)
    } else {
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
  } else {
    Write-Host ("[skip] {0} not managed by stack state" -f $Service.Name)
  }

  if ($IncludeUnmanaged) {
    $exclude = @()
    if ($existing) {
      $exclude += [int]$existing.pid
    }
    $extraPids = Find-ServiceProcessIds -Service $Service -ExcludePids $exclude
    foreach ($candidatePid in $extraPids) {
      $pidValue = [int]$candidatePid
      if (-not (Test-PidRunning -ProcessId $pidValue)) {
        continue
      }
      try {
        taskkill /PID $pidValue /T /F | Out-Null
        Write-Host ("[stop-unmanaged] {0} pid={1}" -f $Service.Name, $pidValue)
      } catch {
        Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
      }
    }
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
      if ($entry) {
        Write-Host ("   logs: out={0} err={1}" -f $entry.stdout_log, $entry.stderr_log)
      }
    } else {
      Write-Host (" - {0}: managed={1} pid={2} running={3}" -f $svc.Name, $managed, $procId, $running)
      if ($entry) {
        Write-Host ("   logs: out={0} err={1}" -f $entry.stdout_log, $entry.stderr_log)
      }
    }
  }
}

function Normalize-CommandText {
  param([string]$Value)
  if ([string]::IsNullOrWhiteSpace($Value)) {
    return ""
  }
  return ($Value.ToLower().Replace("/", "\"))
}

function Get-ServiceNeedles {
  param([pscustomobject]$Service)
  $needles = @()
  if ($Service.PSObject.Properties.Match("MatchArgs").Count -gt 0 -and $Service.MatchArgs) {
    foreach ($arg in $Service.MatchArgs) {
      if (-not [string]::IsNullOrWhiteSpace([string]$arg)) {
        $needles += (Normalize-CommandText -Value ([string]$arg))
      }
    }
  }
  if ($needles.Count -eq 0) {
    $needles += (Normalize-CommandText -Value ([string]$Service.Script))
  }
  return $needles
}

function Find-ServiceProcessIds {
  param(
    [pscustomobject]$Service,
    [int[]]$ExcludePids = @()
  )
  $needles = Get-ServiceNeedles -Service $Service
  $exclude = @{}
  foreach ($excludePid in $ExcludePids) {
    if ($excludePid -gt 0) {
      $exclude[[int]$excludePid] = $true
    }
  }

  $matches = @()
  try {
    $rows = Get-CimInstance Win32_Process -ErrorAction Stop
  } catch {
    return @()
  }
  foreach ($row in $rows) {
    $rowPid = [int]$row.ProcessId
    if ($rowPid -le 0 -or $exclude.ContainsKey($rowPid)) {
      continue
    }
    $cmd = Normalize-CommandText -Value ([string]$row.CommandLine)
    if ([string]::IsNullOrWhiteSpace($cmd)) {
      continue
    }
    $isMatch = $false
    foreach ($needle in $needles) {
      if ($needle -and $cmd.Contains($needle)) {
        $isMatch = $true
        break
      }
    }
    if ($isMatch) {
      $matches += $rowPid
    }
  }
  return @($matches | Sort-Object -Unique)
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
  param([switch]$IncludeUnmanaged)
  $state = Read-StackState
  $reverse = Get-ReverseServices
  foreach ($svc in $reverse) {
    Stop-ServiceProcess -Service $svc -StateTable $state -IncludeUnmanaged:$IncludeUnmanaged
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
    Stop-Stack -IncludeUnmanaged
  }
  "restart" {
    Stop-Stack -IncludeUnmanaged
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
