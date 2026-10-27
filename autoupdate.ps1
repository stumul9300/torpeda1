# Тихое автообновление «Торпеды» при запуске start.bat.
# Сравнивает версию на GitHub с установленной и, если есть новая, скачивает и копирует файлы поверх.
# Любая ошибка (нет интернета, закрытый репозиторий) не мешает запуску: программа просто стартует как есть.
# Ключи и база лежат в %LOCALAPPDATA%\Torpeda и не трогаются; .venv и data пропускаются.
# Код выхода: 0 = ничего не изменилось, 2 = файлы обновлены (start.bat перезапустится сам).
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$repo = "stumul9300/torpeda1"
$stamp = Join-Path $root ".installed-commit"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

try {
    $head = Invoke-RestMethod "https://api.github.com/repos/$repo/commits/main" -TimeoutSec 8 `
        -Headers @{ "User-Agent" = "torpeda-autoupdate"; "Accept" = "application/vnd.github.sha" }
    $sha = ([string]$head).Trim()
    if ($sha -notmatch '^[0-9a-f]{40}$') { exit 0 }
    $have = if (Test-Path $stamp) { (Get-Content $stamp -Raw).Trim() } else { "" }
    if ($sha -eq $have) { exit 0 }

    Write-Host "Найдена новая версия, обновляю..."
    $tmp = Join-Path $env:TEMP ("torpeda-update-" + [guid]::NewGuid())
    New-Item $tmp -ItemType Directory | Out-Null
    $zip = Join-Path $tmp "main.zip"
    Invoke-WebRequest "https://github.com/$repo/archive/$sha.zip" -OutFile $zip -TimeoutSec 120 `
        -Headers @{ "User-Agent" = "torpeda-autoupdate" }
    Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $tmp "x")
    $src = Get-ChildItem (Join-Path $tmp "x") -Directory | Select-Object -First 1
    if (-not $src -or -not (Test-Path (Join-Path $src.FullName "backend\pyproject.toml"))) { throw "в архиве нет программы" }

    robocopy $src.FullName $root /E /XD .venv data /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "не получилось скопировать файлы" }
    Set-Content $stamp $sha -Encoding ASCII
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Обновлено." -ForegroundColor Green
    exit 2
} catch {
    Write-Host "Автообновление пропущено: $($_.Exception.Message)"
    exit 0
}
