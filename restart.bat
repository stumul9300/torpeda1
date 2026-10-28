@echo off
rem restart: wait for the old window to close, then run start.bat again (it updates files itself)
ping -n 6 127.0.0.1 >nul
start "" "%~dp0start.bat"
