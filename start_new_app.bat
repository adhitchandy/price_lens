@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run setup_windows.bat first.
    pause
    exit /b 1
)
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
title Price Lens
echo Starting Price Lens. Your browser opens by itself.
echo Keep this window open while you use the app; close it to stop the app.
echo.
".venv\Scripts\python.exe" -m price_lens.webapp
if errorlevel 1 pause
endlocal
