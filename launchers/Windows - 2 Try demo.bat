@echo off
cd /d "%~dp0\.."
if not exist ".venv\Scripts\activate.bat" (
  echo Run "Windows - 1 Setup.bat" first.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
echo Made-up data only: nothing is read from or sent to Gmail or Zoho.
sales-pipeline ui --demo
pause
