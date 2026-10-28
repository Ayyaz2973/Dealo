@echo off
cd /d "%~dp0"
title Dealo - Property Manager
if "%OLLAMA_MODEL%"=="" set OLLAMA_MODEL=hermes3:8b
echo ========================================================
echo       Dealo - Smart Real Estate Management System
echo ========================================================
echo.
echo Server start ho raha hai...
echo Browser mein http://127.0.0.1:8000 automatically open hoga.
echo.
start "" cmd /c "timeout /t 2 >nul & start http://127.0.0.1:8000"
python main.py
echo.
echo Server band ho gaya.
pause
