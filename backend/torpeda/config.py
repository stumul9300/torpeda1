"""Настройки приложения.

Ключи WB (keys.json) и база (torpeda.db) лежат в постоянной папке вне программы:
на Windows это папка Torpeda внутри %LOCALAPPDATA%, поэтому обновление программы их не стирает.
Другую папку можно задать переменной TORPEDA_DATA_DIR.
Ключ, сохранённый в программе, важнее всего. Переменные окружения и файл backend/.env используются,
только если в программе ключ не сохранён.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent



def default_data_dir() -> Path:
    if custom := os.getenv("TORPEDA_DATA_DIR"):
        return Path(custom)
    if local := os.getenv("LOCALAPPDATA"):  # Windows
        return Path(local) / "Torpeda"
    return Path(os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "torpeda"


DATA_DIR = default_data_dir()
KEYS_FILE = DATA_DIR / "keys.json"
OLD_DATA_DIR = BACKEND_DIR / "data"  # до версии с постоянной папкой данные лежали здесь
DATA_FILES = ("keys.json", "torpeda.db")

load_dotenv(BACKEND_DIR / ".env")

KEY_NAMES = {"read": "WB_API_TOKEN", "prices": "WB_PRICES_TOKEN"}


def migrate_old_data() -> list[str]:
    """Один раз переносит ключи и базу из старой папки backend/data. Уже перенесённое не трогает."""
    moved = []
    for name in DATA_FILES:
        old, new = OLD_DATA_DIR / name, DATA_DIR / name
        if old.exists() and not new.exists():
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old, new)
            moved.append(name)
    return moved


def read_keys_file() -> dict[str, str]:
    try:
        return json.loads(KEYS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_keys(values: dict[str, str]) -> None:
    """Сохраняет ключи, введённые в интерфейсе. Пустая строка удаляет ключ."""
    keys = read_keys_file()
    for name, value in values.items():
        if name not in KEY_NAMES:
            raise ValueError(f"Неизвестный ключ: {name}")
        if value := clean_key(value):
            keys[name] = value
        else:
            keys.pop(name, None)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    KEYS_FILE.write_text(json.dumps(keys), encoding="utf-8")


def clean_key(value: str) -> str:
    """Ключ без пробелов и переносов строк, которые попадают при копировании: в самом ключе WB их не бывает."""
    return re.sub(r"\s+", "", value or "")


def key_source(name: str) -> tuple[str, str]:
    """Ключ и откуда он взят: сохранённый в программе важнее .env и переменных окружения."""
    if saved := read_keys_file().get(name, ""):
        return saved, "программа"
    env_name = KEY_NAMES[name]
    if from_env := clean_key(os.getenv(env_name, "")):
        in_dotenv = clean_key(dotenv_values(BACKEND_DIR / ".env").get(env_name) or "") == from_env
        return from_env, "файл backend\\.env" if in_dotenv else "переменная окружения Windows"
    return "", ""


def _key(name: str) -> str:
    return key_source(name)[0]


def masked_keys() -> dict[str, str | None]:
    """Для показа в интерфейсе: только последние 4 символа."""
    return {name: ("…" + k[-4:]) if (k := _key(name)) else None for name in KEY_NAMES}


@dataclass(frozen=True)
class Settings:
    wb_api_token: str  # ключ «только чтение»: товары, цены, статистика, акции
    wb_prices_token: str  # ключ «чтение и запись» только для категории «Цены и скидки»
    database_url: str


def get_settings() -> Settings:
    migrate_old_data()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    default_db = DATA_DIR / "torpeda.db"
    return Settings(
        wb_api_token=_key("read"),
        wb_prices_token=_key("prices"),
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{default_db}"),
    )
