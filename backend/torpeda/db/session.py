from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import DEFAULT_ACCOUNT_ID, DEFAULT_SETTINGS, Account, Base, Setting, Stock


def make_engine(url: str) -> Engine:
    # облачные базы выдают ссылку вида postgresql://, а драйвер у нас psycopg 3
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg://" + url.removeprefix(prefix)
    if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})


def _drop_outdated_snapshots(engine: Engine) -> None:
    """Таблица остатков — снимок, который заново заполняется при загрузке из WB.
    Если в старой базе у неё другие колонки, проще пересоздать её, чем переделывать."""
    insp = inspect(engine)
    if insp.has_table("stocks") and "scheme" not in {c["name"] for c in insp.get_columns("stocks")}:
        Stock.__table__.drop(engine)


def _add_missing_columns(engine: Engine) -> None:
    """Новые колонки в существующих таблицах старой базы. Они необязательные: данные дозагрузятся из WB."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in existing:
                    ddl = col.type.compile(dialect=engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}'))


def init_db(engine: Engine) -> sessionmaker[Session]:
    """Создаёт таблицы, кабинет по умолчанию и настройки, если их ещё нет."""
    _drop_outdated_snapshots(engine)
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
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
