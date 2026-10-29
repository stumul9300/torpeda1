# Образ для Cloudflare Containers: тот же бэкенд и фронтенд, что запускает start.bat
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/
RUN cd backend && uv sync --no-dev --frozen --no-install-project
COPY backend backend
COPY frontend frontend
WORKDIR /app/backend
ENV TORPEDA_DATA_DIR=/tmp/torpeda
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "--frozen", "uvicorn", "torpeda.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
