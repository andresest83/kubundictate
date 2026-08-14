' Launches start_hidden.bat with no console window -- useful for Windows Startup.
' Output/errors land in kubundictate.log for troubleshooting.
Set objShell = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
objShell.Run """" & scriptDir & "\start_hidden.bat""", 0, False
