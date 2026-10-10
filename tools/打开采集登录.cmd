@echo off
chcp 65001 >nul
cd /d "%~dp0.."
"D:\aaopenclow-share\mediacrawler\.venv\Scripts\python.exe" -X utf8 -B "tools\research\open_social_login.py"
echo.
pause
