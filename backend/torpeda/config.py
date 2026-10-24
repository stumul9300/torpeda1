"""Настройки приложения. Читаются из переменных окружения и локального файла backend/.env.

Файл .env лежит только на компьютере пользователя и не попадает в репозиторий (.gitignore).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BACKEND_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    wb_api_token: str  # ключ «только чтение»: товары, цены, статистика, акции
    wb_prices_token: str  # ключ «чтение и запись» только для категории «Цены и скидки»
    database_url: str


def get_settings() -> Settings:
    default_db = BACKEND_DIR / "data" / "torpeda.db"
    return Settings(
        wb_api_token=os.getenv("WB_API_TOKEN", "").strip(),
        wb_prices_token=os.getenv("WB_PRICES_TOKEN", "").strip(),
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{default_db}"),
    )
