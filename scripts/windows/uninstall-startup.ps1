$startup = [Environment]::GetFolderPath("Startup")
$shortcut = Join-Path $startup "PhD Notion Dashboard.lnk"

if (Test-Path $shortcut) {
    Remove-Item $shortcut -Force
    Write-Host "Removed PhD Notion Dashboard from Windows Startup."
} else {
    Write-Host "Startup entry was not installed."
}
