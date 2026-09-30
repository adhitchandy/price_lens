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
".venv\Scripts\python.exe" -m streamlit run apps\unified_app.py
