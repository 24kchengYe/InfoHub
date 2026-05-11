' InfoHub Silent Startup (no console window)
' Place a shortcut to this file in shell:startup for auto-start

Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")

Dim infohubDir
infohubDir = "D:\InfoHub"

' Create logs directory
If Not FSO.FolderExists(infohubDir & "\logs") Then
    FSO.CreateFolder(infohubDir & "\logs")
End If

' Set proxy environment
WshShell.Environment("PROCESS")("HTTP_PROXY") = "http://127.0.0.1:2080"
WshShell.Environment("PROCESS")("HTTPS_PROXY") = "http://127.0.0.1:2080"
WshShell.Environment("PROCESS")("PYTHONIOENCODING") = "utf-8"

' Start Backend (FastAPI)
WshShell.Run "cmd /c ""cd /d " & infohubDir & " && D:\InfoHub\.venv\Scripts\python.exe -m src.main > " & infohubDir & "\logs\backend.log 2>&1""", 0, False

' Wait for backend
WScript.Sleep 4000

' Start Frontend (Next.js production)
WshShell.Run "cmd /c ""cd /d " & infohubDir & "\frontend && npx next start -p 3000 > " & infohubDir & "\logs\frontend.log 2>&1""", 0, False
