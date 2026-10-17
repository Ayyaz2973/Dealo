@echo off
title Dealo - Stopping Server
echo ========================================================
echo       Dealo Property Management System - Stop
echo ========================================================
echo Port 8000 par chalne wale server ko band kiya ja raha hai...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000') do (
    taskkill /F /PID %%a 2>nul
)
echo Dealo server band ho gaya.
timeout /t 2 >nul
