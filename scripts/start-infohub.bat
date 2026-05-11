@echo off
chcp 65001 >nul 2>&1
title InfoHub Service

:: Set environment
set INFOHUB_DIR=D:\InfoHub
set HTTP_PROXY=http://127.0.0.1:2080
set HTTPS_PROXY=http://127.0.0.1:2080
set PYTHONIOENCODING=utf-8

:: Start Backend (FastAPI on port 18899)
echo [InfoHub] Starting backend on port 18899...
cd /d "%INFOHUB_DIR%"
start /b "" cmd /c "cd /d %INFOHUB_DIR% && D:\InfoHub\.venv\Scripts\python.exe -m src.main > %INFOHUB_DIR%\logs\backend.log 2>&1"

:: Wait for backend to be ready
timeout /t 3 /nobreak >nul

:: Start Frontend (Next.js on port 3000)
echo [InfoHub] Starting frontend on port 3000...
cd /d "%INFOHUB_DIR%\frontend"
start /b "" cmd /c "cd /d %INFOHUB_DIR%\frontend && npx next start -p 3000 > %INFOHUB_DIR%\logs\frontend.log 2>&1"

echo [InfoHub] Services started.
echo   Backend:  http://127.0.0.1:18899
echo   Frontend: http://localhost:3000
