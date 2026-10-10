$ErrorActionPreference = "Stop"

Write-Host "Installing PhD Notion Dashboard..." -ForegroundColor Cyan

$python = Get-Command py -ErrorAction SilentlyContinue

if (-not $python) {
    $python = Get-Command python -ErrorAction SilentlyContinue
}

if (-not $python) {
    throw "Python was not found. Install Python 3.10+ first."
}

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    py -3 -m venv .venv
}

Write-Host "Installing Python dependencies..."
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt

Write-Host "Generating app icon..."
& ".\.venv\Scripts\python.exe" app_icon.py

Write-Host ""
Write-Host "Installation complete." -ForegroundColor Green
Write-Host ""
Write-Host "Next:"
Write-Host "  1. Run: .\.venv\Scripts\python.exe setup.py"
Write-Host "  2. Test: .\.venv\Scripts\python.exe main.py"
Write-Host "  3. Startup: .\install-startup.ps1"
