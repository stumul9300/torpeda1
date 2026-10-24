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
  torpeda/db/       база данных SQLite (backend/data/torpeda.db)
  torpeda/wb_api/   клиент API Wildberries
  torpeda/sync.py   загрузка данных из WB в базу
  torpeda/services.py таблица товаров и анализ акций
  torpeda/pricing.py отправка цен: предпросмотр, подтверждение, журнал, возврат
  torpeda/importers/ импорт Excel/CSV (запасной способ, позже)
  tests/            тесты на эталонах из «Ракеты»
frontend/           интерфейс в браузере (таблица, акции, журнал цен, настройки)
start.bat           запуск двойным щелчком на Windows
docs/formulas.md    формулы и сверка с «Ракетой»
```

## Запуск

На Windows: двойной щелчок по `start.bat`, ключи WB вставляются на вкладке «Настройки». Подробно: [docs/setup-api.md](docs/setup-api.md).

Коротко (нужен [uv](https://docs.astral.sh/uv/)):

```bash
cd backend
uv sync
cp .env.example .env      # или вставить ключи в интерфейсе
uv run pytest            # тесты
uv run python -m torpeda.sync check   # проверить связь с WB
uv run python -m torpeda.sync all     # загрузить данные
uv run uvicorn torpeda.api.app:app --reload   # интерфейс на http://127.0.0.1:8000/
```

Отчёты WB, базы данных и токены в репозиторий не кладутся (см. `.gitignore`).
