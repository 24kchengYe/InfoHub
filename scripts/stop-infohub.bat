@echo off
echo [InfoHub] Stopping services...

:: Kill backend (python on port 18899)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":18899" ^| findstr "LISTENING"') do (
    echo Killing backend PID %%a
    taskkill /F /PID %%a >nul 2>&1
)

:: Kill frontend (node on port 3000)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000" ^| findstr "LISTENING"') do (
    echo Killing frontend PID %%a
    taskkill /F /PID %%a >nul 2>&1
)

echo [InfoHub] Services stopped.
