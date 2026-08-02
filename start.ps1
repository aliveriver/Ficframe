param(
  [string]$HostAddress = "127.0.0.1",
  [int]$Port = 8787
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Host "[FicFrame] uv was not found."
  Write-Host "Please install uv first: https://docs.astral.sh/uv/"
  Read-Host "Press Enter to exit"
  exit 1
}

$env:UV_CACHE_DIR = ".uv-cache"

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
  Copy-Item ".env.example" ".env"
  Write-Host "[FicFrame] Created .env from .env.example."
}

Write-Host "[FicFrame] Installing or checking dependencies..."
uv sync

$url = "http://${HostAddress}:${Port}"
Write-Host "[FicFrame] Opening $url"
Start-Process $url

Write-Host "[FicFrame] Starting server. Press Ctrl+C to stop."
uv run ficframe serve --host $HostAddress --port $Port
