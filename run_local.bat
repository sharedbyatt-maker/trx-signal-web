@echo off
setlocal
cd /d "%~dp0"
set TRX_PYTHON_CMD=python
where py >nul 2>nul && set TRX_PYTHON_CMD=py -3
%TRX_PYTHON_CMD% -c "import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)" >nul 2>nul
if errorlevel 1 (
  echo Install Python 3.12 or newer and enable Add python.exe to PATH.
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe (
  echo Creating virtual environment...
  %TRX_PYTHON_CMD% -m venv .venv
  if errorlevel 1 (
    echo Virtual environment creation failed.
    pause
    exit /b 1
  )
)
echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo Package installation failed. Read the error above.
  pause
  exit /b 1
)
set PORT=5000
set ADMIN_COOKIE_SECURE=0
set TRX_ORDER_ENABLED=0
if "%TRX_LOCAL_REAL_ORDERS%"=="1" set TRX_ORDER_ENABLED=1
echo.
echo Site:  http://localhost:5000
echo Admin: http://localhost:5000/admin
if "%TRX_ORDER_ENABLED%"=="1" (echo REAL orders: enabled - buttons use your real balance.) else (echo REAL orders: disabled.)
echo Stop with Ctrl+C.
echo.
".venv\Scripts\python.exe" app.py
pause
endlocal
