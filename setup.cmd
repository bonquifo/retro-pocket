@echo off
rem Retro Pocket for Windows: create the Python environment, install pygame-ce
rem and download the emulators into emulators\ (see tools\setup_windows.py).
rem Run it again at any time to repair or update. Arguments go to setup_windows.py.
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto :packages
set "PY="
for %%V in (3.12 3.13 3.11 3.14) do (
  if not defined PY (
    py -%%V -c "pass" >nul 2>nul && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo Python 3.11 or newer is needed: https://www.python.org/downloads/windows/
  goto :fail
)
echo Creating the Python environment with %PY% ...
%PY% -m venv .venv || goto :fail

:packages
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :fail
".venv\Scripts\python.exe" tools\setup_windows.py %* || goto :fail
echo.
echo Setup complete. Put your game dumps in the roms folder and start "RetroPocket.cmd".
exit /b 0

:fail
echo.
echo Setup did not finish; see the messages above.
exit /b 1
