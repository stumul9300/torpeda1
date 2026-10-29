@echo off
rem restart: wait until the old program frees port 8000 (up to 60 s), then run start.bat again (it updates files itself)
setlocal enabledelayedexpansion
set n=0
:wait
ping -n 3 127.0.0.1 >nul
netstat -ano | findstr /r /c:":8000 .*LISTENING" >nul
if not errorlevel 1 (
  set /a n+=1
  if !n! lss 30 goto wait
)
start "" "%~dp0start.bat"
