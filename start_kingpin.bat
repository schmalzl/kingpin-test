@echo off
REM Starts Kingpin for public hosting behind a tunnel. Double-click, or run from a terminal.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Creating virtual environment...
  py -3 -m venv .venv || (echo Python 3.10+ is required: https://www.python.org/downloads/ & pause & exit /b 1)
)
call .venv\Scripts\activate.bat
python -m pip install -q -r requirements.txt
set KINGPIN_ENV=production
set KINGPIN_TRUST_PROXY=1
python serve.py
pause
