@echo off
title LCT2026 Wine Label Search
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Script finished with exit code %ERRORLEVEL%
    pause
)
