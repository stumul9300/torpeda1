from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import DEFAULT_ACCOUNT_ID, DEFAULT_SETTINGS, Account, Base, Setting


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})


def init_db(engine: Engine) -> sessionmaker[Session]:
    """Создаёт таблицы, кабинет по умолчанию и настройки, если их ещё нет."""
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as s:
        if s.get(Account, DEFAULT_ACCOUNT_ID) is None:
            s.add(Account(id=DEFAULT_ACCOUNT_ID, name="Мой кабинет"))
        existing = set(s.scalars(select(Setting.key).where(Setting.account_id == DEFAULT_ACCOUNT_ID)))
        for key, value in DEFAULT_SETTINGS.items():
            if key not in existing:
                s.add(Setting(account_id=DEFAULT_ACCOUNT_ID, key=key, value=value))
        s.commit()
    return factory
