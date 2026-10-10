# Installs the dashboard into .venv in the project folder.
#   .\scripts\windows\install.ps1          # dashboard only
#   .\scripts\windows\install.ps1 -Voice   # with voice notes
param([switch]$Voice)

$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path "$PSScriptRoot\..\..")

Write-Host "Installing PhD Notion Dashboard..." -ForegroundColor Cyan

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python was not found. Install Python 3.11+ from python.org first."
}

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    py -3 -m venv .venv
}

$python = ".\.venv\Scripts\python.exe"
$target = if ($Voice) { ".[voice]" } else { "." }

Write-Host "Installing Python packages..."
& $python -m pip install --upgrade pip
& $python -m pip install -e $target

Write-Host ""
Write-Host "Installation complete." -ForegroundColor Green
Write-Host ""
Write-Host "Next:"
Write-Host "  1. Start:   .\.venv\Scripts\notion-dashboard.exe   (first start asks for your Notion token)"
Write-Host "  2. Startup: .\scripts\windows\install-startup.ps1"
