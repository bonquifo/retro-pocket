@echo off
rem Start Retro Pocket without a console window. Options are passed on
rem (for example --all, --roms-dir D:\Games, --no-cover-downloads; see app.py --help).
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
  echo Retro Pocket is not set up yet: run setup.cmd first.
  pause
  exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0app.py" %*
