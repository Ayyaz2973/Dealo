@echo off
cd /d "%~dp0"
title Dealo - Installing Dependencies
echo ========================================================
echo       Dealo Property Management System - Setup
echo ========================================================
echo.
echo Installing Python dependencies...
python -m pip install -r requirements.txt
echo.
echo ========================================================
echo Installation mukammal ho gayi hai!
echo Ab aap start.bat chala kar Dealo open kar sakte hain.
echo ========================================================
pause
