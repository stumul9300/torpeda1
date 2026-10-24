# Торпеда

Веб-приложение для продавца Wildberries: таблица товаров с юнит-экономикой,
изменение цены с мгновенным пересчётом маржи, контроль убыточных товаров, анализ акций,
история продаж, финансовая аналитика и остатки.

Версия 1.0 — для одного кабинета, запускается локально.

## Структура

```
backend/            Python 3.12+, FastAPI
  torpeda/calc/     расчётный модуль: юнит-экономика, логистика, фактическая прибыль
  torpeda/api/      HTTP API для интерфейса
  torpeda/db/       база данных (этап 1.2)
  torpeda/importers/ импорт Excel/CSV (этап 1.2)
  torpeda/wb_api/   API Wildberries (этап 2)
  tests/            тесты на эталонах из «Ракеты»
frontend/           интерфейс (этап 1.3)
docs/formulas.md    формулы и сверка с «Ракетой»
```

## Запуск

Нужен [uv](https://docs.astral.sh/uv/).

```bash
cd backend
uv sync
uv run pytest            # тесты
uv run uvicorn torpeda.api.app:app --reload   # API на http://127.0.0.1:8000/docs
```

Отчёты WB, базы данных и токены в репозиторий не кладутся (см. `.gitignore`).
