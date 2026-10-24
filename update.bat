@echo off
chcp 65001 >nul
rem Обновление запускается в отдельном окне: этот файл тоже обновится, а cmd читает .bat по ходу выполнения
if not exist "%~dp0update.ps1" (
  echo Не нашла update.ps1 рядом с update.bat. Скачайте программу заново.
  pause
  exit /b 1
)
start "Обновление Торпеды" powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1" "%~1"
exit /b 0
