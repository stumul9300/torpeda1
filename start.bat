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

set "VER="
for /f "tokens=2 delims==" %%v in ('findstr /b "__version__" "%ROOT%backend\torpeda\__init__.py"') do set "VER=%%v"
echo Торпеда, версия:%VER%
echo Папка программы: %ROOT%
echo.

rem если программа уже запущена (например, старая копия в другом окне), новая не сможет открыться
netstat -ano | findstr /r /c:":8000 .*LISTENING" >nul
if not errorlevel 1 (
  echo Программа уже запущена в другом окне, возможно старая версия или другая папка.
  echo Закройте все чёрные окна «Торпеда» и запустите start.bat снова.
  echo Если окон не видно, перезагрузите компьютер.
  echo.
  pause
  exit /b 1
)

rem uv ставит Python и все библиотеки сам
where uv >nul 2>nul
if errorlevel 1 (
  echo Первый запуск: устанавливаю uv...
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)

echo Проверяю библиотеки...
set "UV_PYTHON_PREFERENCE=only-managed"
uv sync --no-dev --python 3.12
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
uv run --no-dev --python 3.12 uvicorn torpeda.api.app:app --host 127.0.0.1 --port 8000
pause
