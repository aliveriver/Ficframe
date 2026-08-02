param(
  [string]$HostAddress = "127.0.0.1",
  [int]$Port = 8787
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$env:PIP_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"

function Find-Uv {
  $command = Get-Command uv -ErrorAction SilentlyContinue
  if ($command) {
    return $command.Source
  }

  $candidates = @(
    "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe",
    "$env:USERPROFILE\.cargo\bin\uv.exe",
    "$env:USERPROFILE\.local\bin\uv.exe"
  )
  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) {
      return $candidate
    }
  }
  return $null
}

function Find-Python {
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) {
    return @($py.Source, "-3")
  }
  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) {
    return @($python.Source)
  }
  return $null
}

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
  Copy-Item ".env.example" ".env"
  Write-Host "[FicFrame] Created .env from .env.example."
}

$uv = Find-Uv
if ($uv) {
  Write-Host "[FicFrame] uv found. Using uv environment."
  $env:UV_CACHE_DIR = ".uv-cache"
  & $uv sync

  $url = "http://${HostAddress}:${Port}"
  Write-Host "[FicFrame] Opening $url"
  Start-Process $url

  Write-Host "[FicFrame] Starting server with uv. Press Ctrl+C to stop."
  & $uv run ficframe serve --host $HostAddress --port $Port
  exit $LASTEXITCODE
}

Write-Host "[FicFrame] uv was not found. Falling back to Python venv + pip."
$python = Find-Python
if (-not $python) {
  Write-Host "[FicFrame] Python 3.10+ was not found."
  Write-Host "Please install Python from https://www.python.org/downloads/"
  Write-Host "During installation, enable 'Add python.exe to PATH'."
  Read-Host "Press Enter to exit"
  exit 1
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
  Write-Host "[FicFrame] Creating virtual environment..."
  $pythonArgs = @()
  if ($python.Length -gt 1) {
    $pythonArgs = $python[1..($python.Length - 1)]
  }
  & $($python[0]) @pythonArgs -m venv .venv
}

Write-Host "[FicFrame] Installing or checking dependencies with pip..."
& ".\.venv\Scripts\python.exe" -m pip install -U pip -i $env:PIP_INDEX_URL
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt -i $env:PIP_INDEX_URL

$fallbackUrl = "http://${HostAddress}:${Port}"
Write-Host "[FicFrame] Opening $fallbackUrl"
Start-Process $fallbackUrl

Write-Host "[FicFrame] Starting server with Python venv. Press Ctrl+C to stop."
& ".\.venv\Scripts\python.exe" -m ficframe.cli serve --host $HostAddress --port $Port
