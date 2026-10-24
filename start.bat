@echo off
chcp 65001 >nul
title Торпеда

rem папка, где лежит этот файл, откуда бы его ни запустили
set "ROOT=%~dp0"
cd /d "%ROOT%"

rem при запуске прямо из ZIP Windows кладёт один start.bat во временную папку
if exist "%ROOT%backend\pyproject.toml" goto found
echo.
echo Не нашла папку backend рядом с start.bat.
echo Файл запущен из папки: %ROOT%
echo.
echo Скорее всего, start.bat открыт прямо из архива ZIP. Что сделать:
echo   1. Правой кнопкой по архиву, «Извлечь все...», затем «Извлечь».
echo   2. Откройте распакованную папку: в ней должны быть папки backend и frontend.
echo   3. Дважды щёлкните start.bat уже там.
echo.
pause
exit /b 1

:found
cd /d "%ROOT%backend"

rem uv ставит Python и все библиотеки сам
where uv >nul 2>nul
if errorlevel 1 (
  echo Первый запуск: устанавливаю uv...
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)

echo Проверяю библиотеки...
uv sync --no-dev
if errorlevel 1 (
  echo Не получилось установить библиотеки. Пришлите скриншот этого окна.
  pause
  exit /b 1
)

rem браузер откроется через 4 секунды, когда программа запустится
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8000/"
echo.
echo Торпеда работает: http://127.0.0.1:8000/
echo Не закрывайте это окно, пока пользуетесь программой.
echo.
uv run --no-dev uvicorn torpeda.api.app:app --host 127.0.0.1 --port 8000
pause
