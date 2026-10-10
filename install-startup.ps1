$ErrorActionPreference = "Stop"

$project = (Resolve-Path ".").Path
$python = Join-Path $project ".venv\Scripts\pythonw.exe"
$main = Join-Path $project "main.py"

if (-not (Test-Path $python)) {
    throw "Virtual environment not found. Run install.ps1 first."
}

if (-not (Test-Path $main)) {
    throw "main.py not found."
}

$startup = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startup "PhD Notion Dashboard.lnk"

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)

$shortcut.TargetPath = $python
$shortcut.Arguments = "`"$main`""
$shortcut.WorkingDirectory = $project
$shortcut.Description = "PhD Notion Dashboard"
$icon = Join-Path $project "assets\icon.ico"
if (Test-Path $icon) {
    $shortcut.IconLocation = $icon
}
$shortcut.WindowStyle = 7
$shortcut.Save()

Write-Host ""
Write-Host "Installed to Windows Startup:" -ForegroundColor Green
Write-Host $shortcutPath
Write-Host ""
Write-Host "The dashboard will launch automatically when you log into Windows."
