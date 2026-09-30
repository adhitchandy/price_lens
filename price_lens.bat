@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Local environment not found. Run setup_windows.bat first.
    exit /b 1
)

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
".venv\Scripts\python.exe" -m price_lens.cli %*
exit /b %errorlevel%
