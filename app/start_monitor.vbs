' gsv-tts monitor launcher - zero window (no console flash)
' Run this instead of start_monitor.bat if you dislike the brief cmd window.
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = root
sh.Run Chr(34) & root & "\python\pythonw.exe" & Chr(34) & " " & Chr(34) & root & "\monitor\monitor.py" & Chr(34), 0, False
