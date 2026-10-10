' Starts the dashboard without a console window (double-click to run).
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
project = fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName)))
python = project & "\.venv\Scripts\pythonw.exe"

shell.CurrentDirectory = project
shell.Run """" & python & """ -m notion_dashboard", 0, False
