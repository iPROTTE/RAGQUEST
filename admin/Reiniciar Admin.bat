@echo off
cd /d "%~dp0"
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8766 " ^| findstr LISTENING') do taskkill /F /T /PID %%p >nul 2>&1
timeout /t 2 >nul
start "" "%~dp0Ragquest Admin.bat"
