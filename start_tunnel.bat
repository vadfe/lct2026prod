@echo off
setlocal
cd /d "%~dp0"

title LCT2026 PROD - Cloudflare Tunnel Bridge

echo ======================================================================
echo      LCT2026 PROD: Cloudflare Tunnel Bridge to RTX 3090
echo ======================================================================
echo.
echo [1/2] Checking local backend (http://127.0.0.1:8030)...
echo Make sure your Docker container is running!
echo.
echo [2/2] Starting secure HTTPS tunnel...
echo.
echo ======================================================================
echo  Look for the HTTPS link below (e.g., https://xxxx.trycloudflare.com):
echo  Copy that URL and paste it in the web scanner (Settings icon).
echo ======================================================================
echo.
taskkill /F /IM cloudflared.exe >nul 2>&1

:: Используем cloudflared.exe из папки D:\VINA\bin
"D:\VINA\bin\cloudflared.exe" tunnel --protocol http2 --url http://127.0.0.1:8030

pause
