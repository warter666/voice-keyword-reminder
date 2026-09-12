@echo off
rem Run voice reminder with the project venv (no activation needed)
rem Use HF mirror for model downloads (hf-mirror.com reachable in CN)
set HF_ENDPOINT=https://hf-mirror.com
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [!] .venv not found. Run: python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)
".venv\Scripts\python.exe" reminder.py
pause
