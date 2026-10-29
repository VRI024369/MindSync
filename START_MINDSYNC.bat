@echo off
setlocal
cd /d "%~dp0"
echo ==========================================
echo       MindSync - Automatic Starter
echo ==========================================
where py >nul 2>nul
if errorlevel 1 (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python was not found. Install Python 3 from https://www.python.org/downloads/ and tick "Add Python to PATH".
    pause
    exit /b 1
  )
  set PYTHON=python
) else (
  set PYTHON=py
)
if not exist "venv\Scripts\python.exe" (
  echo [1/3] Creating virtual environment...
  %PYTHON% -m venv venv
  if errorlevel 1 goto failed
)
echo [2/3] Installing required packages (first run may take a few minutes)...
"venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed
"venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo [3/3] Starting MindSync...
echo When Flask starts, open http://127.0.0.1:5000 in your browser.
start "" http://127.0.0.1:5000
"venv\Scripts\python.exe" app.py
pause
exit /b 0
:failed
echo.
echo Something went wrong. Check the error above. Make sure Python is installed and connected to the internet for package installation.
pause
exit /b 1
