# Обновление «Торпеды»: скачивает новую версию через браузер (там уже есть вход в GitHub),
# распаковывает поверх программы и запускает её. Ключи и база лежат в %LOCALAPPDATA%\Torpeda и не трогаются.
param([string]$Zip = "")

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$url = "https://github.com/stumul9300/torpeda1/archive/refs/heads/main.zip"

function Fail($text) {
    Write-Host ""
    Write-Host $text -ForegroundColor Red
    Read-Host "Нажмите Enter, чтобы закрыть окно"
    exit 1
}

try {
    if ($Zip -and (Test-Path $Zip)) {
        $file = Get-Item $Zip
    } else {
        $downloads = (New-Object -ComObject Shell.Application).NameSpace("shell:Downloads").Self.Path
        $since = Get-Date
        Write-Host "Открываю скачивание новой версии в браузере..."
        Start-Process $url
        Write-Host "Жду файл torpeda1-main.zip в папке $downloads (до 3 минут)..."
        $file = $null
        for ($i = 0; $i -lt 180 -and -not $file; $i++) {
            Start-Sleep -Seconds 1
            $file = Get-ChildItem $downloads -Filter "torpeda1-main*.zip" -ErrorAction SilentlyContinue |
                Where-Object { $_.LastWriteTime -gt $since } |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1
        }
        if (-not $file) {
            Fail "Файл не появился в папке «Загрузки». Если браузер сохранил его в другое место, перетащите скачанный ZIP мышкой на update.bat."
        }
        Start-Sleep -Seconds 2  # браузер мог ещё не отпустить файл
    }

    $tmp = Join-Path $env:TEMP ("torpeda-update-" + [guid]::NewGuid())
    Write-Host "Распаковываю $($file.Name)..."
    Expand-Archive -LiteralPath $file.FullName -DestinationPath $tmp
    $src = Get-ChildItem $tmp -Directory | Select-Object -First 1
    if (-not $src -or -not (Test-Path (Join-Path $src.FullName "backend\pyproject.toml"))) {
        Fail "В архиве нет программы «Торпеда». Пришлите скриншот этого окна."
    }

    # останавливаем работающую программу, иначе новая не запустится на том же адресе
    Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }

    Write-Host "Обновляю файлы программы..."
    # /E копирует с подпапками и ничего не удаляет; .venv и data не трогаем
    robocopy $src.FullName $root /E /XD .venv data /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { Fail "Не получилось скопировать файлы (код $LASTEXITCODE). Пришлите скриншот этого окна." }
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue

    Write-Host "Готово. Запускаю программу." -ForegroundColor Green
    Start-Process (Join-Path $root "start.bat")
    Start-Sleep -Seconds 3
} catch {
    Fail "Ошибка обновления: $($_.Exception.Message). Пришлите скриншот этого окна."
}
