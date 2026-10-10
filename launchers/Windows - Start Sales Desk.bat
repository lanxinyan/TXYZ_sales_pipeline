@echo off
cd /d "%~dp0\.."
if not exist ".venv\Scripts\activate.bat" (
  echo Run "Windows - 1 Setup.bat" first.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
sales-pipeline ui
pause
