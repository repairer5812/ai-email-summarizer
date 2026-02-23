param(
  [int]$Port = 0,
  [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'

function Run($cmd) {
  Write-Host "> $cmd" -ForegroundColor Cyan
  Invoke-Expression $cmd
}

if (!(Test-Path ".\.venv")) {
  Run "python -m venv .venv"
}

Run "& '.\.venv\Scripts\python.exe' -m pip install -U pip"
Run "& '.\.venv\Scripts\pip.exe' install -r requirements.txt"
Run "& '.\.venv\Scripts\pip.exe' install -e ."

$args = @("serve")
if ($Port -gt 0) { $args += @("--port", "$Port") }
if ($NoBrowser) { $args += "--no-browser" }

Run ("& '.\.venv\Scripts\webmail-summary.exe' " + ($args -join ' '))
