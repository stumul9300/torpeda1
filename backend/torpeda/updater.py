"""Обновление программы кнопкой в интерфейсе.

Сама проверка и замена файлов лежат в autoupdate.ps1, который start.bat запускает при каждом старте.
Здесь только сравнение версии с GitHub и перезапуск через start.bat."""

from __future__ import annotations

import os
import re
import subprocess
import threading

import httpx

from torpeda.config import BACKEND_DIR

ROOT = BACKEND_DIR.parent
REPO = "stumul9300/torpeda1"


class UpdateError(Exception):
    pass


def installed_commit() -> str:
    try:
        return (ROOT / ".installed-commit").read_text(encoding="ascii").strip()
    except OSError:
        return ""


def latest_commit() -> str:
    try:
        resp = httpx.get(
            f"https://api.github.com/repos/{REPO}/commits/main",
            headers={"Accept": "application/vnd.github.sha", "User-Agent": "torpeda-update"},
            timeout=8,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise UpdateError("Не получилось связаться с GitHub. Проверьте интернет.") from exc
    sha = resp.text.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise UpdateError("GitHub вернул непонятный ответ.")
    return sha


def latest_build() -> str | None:
    """Номер сборки на GitHub для подписи кнопки. Не получилось узнать: None, обновление это не блокирует."""
    try:
        resp = httpx.get(
            f"https://raw.githubusercontent.com/{REPO}/main/backend/torpeda/__init__.py",
            headers={"User-Agent": "torpeda-update"},
            timeout=8,
        )
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    m = re.search(r"сборка (\d+)", resp.text)
    return m.group(1) if m else None


def check() -> dict:
    installed, latest = installed_commit(), latest_commit()
    available = installed != latest
    return {
        "installed": installed or None,
        "latest": latest,
        "available": available,
        "build": latest_build() if available else None,
    }


def restart() -> None:
    """Запускает start.bat заново (он сам обновит файлы) и закрывает эту программу."""
    if os.name != "nt":
        raise UpdateError("Перезапуск кнопкой работает только на Windows: запустите программу заново вручную.")
    bat = ROOT / "restart.bat"
    if not bat.exists() or not (ROOT / "start.bat").exists():
        raise UpdateError("Не найден start.bat или restart.bat рядом с программой. Запустите start.bat вручную.")
    # restart.bat подождёт, пока эта программа закроется и освободит порт 8000, и запустит start.bat
    subprocess.Popen(
        ["cmd", "/c", str(bat)],
        cwd=ROOT,
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
    threading.Timer(2.0, lambda: os._exit(0)).start()
