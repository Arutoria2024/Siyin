Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = root & "\app"
sh.Run Chr(34) & root & "\app\python\pythonw.exe" & Chr(34) & " " & Chr(34) & root & "\app\desktop\launch.py" & Chr(34), 0, False
