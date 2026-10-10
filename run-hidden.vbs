Set shell = CreateObject("WScript.Shell")
project = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
python = project & "\.venv\Scripts\pythonw.exe"
main = project & "\main.py"

shell.CurrentDirectory = project
shell.Run """" & python & """ """ & main & """", 0, False
