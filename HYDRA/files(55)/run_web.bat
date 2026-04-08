@echo off
title Hydra AI Surveillance — Web Dashboard
cd /d "%~dp0"

echo ============================================================
echo   HYDRA AI SURVEILLANCE — WEB DASHBOARD
echo   Team Code Warriors / Team Hydra
echo ============================================================
echo.

python --version >nul 2>&1
if %errorlevel% == 0 ( set PYTHON=python ) else ( set PYTHON=python3 )

echo [1/3] Installing requirements...
%PYTHON% -m pip install flask opencv-python ultralytics numpy --quiet
echo.

echo [2/3] Installing web extras...
%PYTHON% -m pip install flask werkzeug --quiet
echo.

echo [3/3] Starting Flask server...
echo.
echo  ✅  Open your browser at: http://localhost:5000
echo  ✅  Press Ctrl+C to stop
echo.

%PYTHON% app/app.py

pause
