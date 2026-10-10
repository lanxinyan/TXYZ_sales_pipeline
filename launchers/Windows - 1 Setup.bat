@echo off
setlocal
cd /d "%~dp0\.."
echo Setting up Sales Desk (one time, about a minute)...
set PY=python
where py >nul 2>nul && set PY=py -3
%PY% -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python 3.10 or newer was not found.
  echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH",
  echo then double-click this file again.
  pause
  exit /b 1
)
%PY% -m venv .venv
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip >nul
pip install -e .
if errorlevel 1 (
  echo Install failed - see the messages above.
  pause
  exit /b 1
)
if not exist .env copy .env.example .env >nul
echo.
sales-pipeline check
echo.
echo Done. Next: "Windows - 2 Try demo.bat" to look around with made-up data.
pause
