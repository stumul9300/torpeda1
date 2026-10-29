# Торпеда на Cloudflare

Каждый пуш в `main` сам выкладывает свежую версию (workflow `deploy.yml`), `update.bat` не нужен.

Как это устроено: Cloudflare Worker (`cloudflare/worker.js`) принимает запросы, спрашивает пароль
и передаёт их в контейнер с той же программой (`Dockerfile`: бэкенд + фронтенд).
Полноценный перенос на «чистые» Python Workers невозможен: нужны SQLAlchemy, curl-cffi и потоки.
Контейнеры Cloudflare требуют платный тариф Workers Paid (5 $/мес).

## Что сделать один раз

1. Cloudflare → Workers & Pages → Plans → включить Workers Paid.
2. Бесплатная база Postgres (например neon.tech): создать проект, скопировать строку подключения
   (`postgresql://...`). Диск контейнера не сохраняется, поэтому себестоимость и журнал цен лежат в этой базе.
3. API-токен Cloudflare: My Profile → API Tokens → Create Token → шаблон «Edit Cloudflare Workers».
   Account ID виден справа на главной странице аккаунта.
4. GitHub → репозиторий → Settings → Secrets and variables → Actions → New repository secret. Добавить:
   - `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`
   - `TORPEDA_PASSWORD`: пароль для входа на сайт (логин любой)
   - `DATABASE_URL`: строка из Neon
   - `WB_API_TOKEN`, `WB_PRICES_TOKEN`, `MPSTATS_TOKEN`: ключи (облачная копия не хранит ключи, введённые в интерфейсе)
5. Actions → deploy → Run workflow (или любой пуш в `main`).

Без `TORPEDA_PASSWORD` сайт не открывается вообще. Вместо пароля можно подключить Cloudflare Access.
