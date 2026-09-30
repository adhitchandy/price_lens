@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Python launcher ^(py^) was not found. Install Python 3.10 or newer first.
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating local virtual environment...
    py -m venv .venv
    if errorlevel 1 exit /b 1
)

echo Installing Price Lens...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 exit /b 1

echo.
echo Running environment checks...
".venv\Scripts\python.exe" -m price_lens.cli doctor
if errorlevel 1 (
    echo.
    echo Setup completed, but one or more checks need attention.
    exit /b 1
)

echo.
echo Setup complete. Start the app by double-clicking start_new_app.bat.
echo To research with an AI agent instead, open this folder in your AI-enabled editor
echo and ask the agent to read agent\SKILL.md first.
endlocal

