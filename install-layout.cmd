@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" -Layout
if errorlevel 1 goto failed
".venv\Scripts\pdf2zh_next.exe" --warmup
if errorlevel 1 goto failed
echo PDF2Zh is ready. Reopen the translation window.
pause
exit /b 0
:failed
echo Setup did not finish. Check the error above and retry.
pause
exit /b 1
