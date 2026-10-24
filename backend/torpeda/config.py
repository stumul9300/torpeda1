"""Настройки приложения.

Ключи WB вводятся на вкладке «Настройки» и хранятся в backend/data/keys.json.
Запасной способ — переменные окружения или файл backend/.env (они важнее файла ключей).
Папка data и файл .env лежат только на компьютере пользователя и не попадают в git (.gitignore).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BACKEND_DIR / "data"
KEYS_FILE = DATA_DIR / "keys.json"

load_dotenv(BACKEND_DIR / ".env")

KEY_NAMES = {"read": "WB_API_TOKEN", "prices": "WB_PRICES_TOKEN"}


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
        if value.strip():
            keys[name] = value.strip()
        else:
            keys.pop(name, None)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    KEYS_FILE.write_text(json.dumps(keys), encoding="utf-8")


def _key(name: str) -> str:
    return os.getenv(KEY_NAMES[name], "").strip() or read_keys_file().get(name, "")


def masked_keys() -> dict[str, str | None]:
    """Для показа в интерфейсе: только последние 4 символа."""
    return {name: ("…" + k[-4:]) if (k := _key(name)) else None for name in KEY_NAMES}


@dataclass(frozen=True)
class Settings:
    wb_api_token: str  # ключ «только чтение»: товары, цены, статистика, акции
    wb_prices_token: str  # ключ «чтение и запись» только для категории «Цены и скидки»
    database_url: str


def get_settings() -> Settings:
    default_db = DATA_DIR / "torpeda.db"
    return Settings(
        wb_api_token=_key("read"),
        wb_prices_token=_key("prices"),
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{default_db}"),
    )
