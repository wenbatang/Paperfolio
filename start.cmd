@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto setup
".venv\Scripts\python.exe" -c "import tkinter, sqlite3, pymupdf, PIL" >nul 2>&1
if not errorlevel 1 goto launch
:setup
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
    if errorlevel 1 (
        pause
        exit /b 1
    )
:launch
start "Paperfolio" ".venv\Scripts\pythonw.exe" "%~dp0app.py"
