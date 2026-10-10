$ErrorActionPreference = "Stop"

$project = (Resolve-Path "$PSScriptRoot\..\..").Path
$python = Join-Path $project ".venv\Scripts\pythonw.exe"

if (-not (Test-Path $python)) {
    throw "Virtual environment not found. Run scripts\windows\install.ps1 first."
}

$startup = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startup "PhD Notion Dashboard.lnk"

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)

$shortcut.TargetPath = $python
$shortcut.Arguments = "-m notion_dashboard"
$shortcut.WorkingDirectory = $project
$shortcut.Description = "PhD Notion Dashboard"
$icon = Join-Path $project "src\notion_dashboard\assets\icon.ico"
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
