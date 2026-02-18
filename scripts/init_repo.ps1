param(
  [string]$Branch = "main"
)

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  $gitCandidates = @(
    "C:\Program Files\Git\cmd",
    "C:\Program Files\Git\bin",
    "C:\Program Files (x86)\Git\cmd",
    "$env:LOCALAPPDATA\Programs\Git\cmd"
  )
  foreach ($candidate in $gitCandidates) {
    if (Test-Path (Join-Path $candidate "git.exe")) {
      $env:Path = "$candidate;$env:Path"
      break
    }
  }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Write-Error "Git was not found in PATH or common install locations. Install Git and rerun this script."
  exit 1
}

git init .
git checkout -b $Branch
git add .
git commit -m "chore: scaffold watchkeeper vNext contracts and schemas"

Write-Host "Repository initialized on branch '$Branch'."
