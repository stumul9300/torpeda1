"""Выгрузка данных MPSTATS по артикулам WB: продажи, цены и остатки по дням.

Документация: https://mpstats.io/api/docs (база https://mpstats.io/api/, заголовок X-Mpstats-TOKEN).
Методы по артикулу WB:
- GET analytics/v1/wb/items/{sku}/full       — карточка и итоги за период (бывший wb/get/item/{sku}/sales)
- GET analytics/v1/wb/items/{sku}/by_period  — продажи, цены и остатки по дням, параметры d1, d2

Токен берётся из MPSTATS_TOKEN (переменная окружения или файл backend/.env) и никуда не выводится.
Ответы сохраняются как есть в папку данных Торпеды (mpstats/), а в консоль печатается сводка.

Запуск:
    uv run python -m torpeda.mpstats                       # артикулы по умолчанию, последние 30 дней
    uv run python -m torpeda.mpstats 482235433 --days 60
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from typing import Any

import httpx
from dotenv import dotenv_values

from torpeda.config import BACKEND_DIR, DATA_DIR, clean_key

BASE = "https://mpstats.io/api/analytics/v1/wb"
DEFAULT_SKUS = (1803104278, 482235433, 955259665, 482235434, 1803104279)
OUT_DIR = DATA_DIR / "mpstats"

# Имена полей в ответах MPSTATS менялись между версиями API: берём первое найденное.
DATE_KEYS = ("data", "date", "day")
SALES_KEYS = ("sales", "orders")
PRICE_KEYS = ("final_price", "finalPrice", "price_with_discount", "price", "basic_price")
BASE_PRICE_KEYS = ("price", "basic_price", "basicPrice")
BALANCE_KEYS = ("balance", "stock", "quantity")
REVENUE_KEYS = ("revenue",)


class MpstatsError(RuntimeError):
    pass


def token_source() -> tuple[str, str]:
    """Токен и откуда он взят: переменная окружения важнее файла, как и для ключей WB."""
    env_file = BACKEND_DIR / ".env"
    from_file = clean_token(dotenv_values(env_file, encoding="utf-8-sig").get("MPSTATS_TOKEN") or "")
    from_env = clean_token(os.getenv("MPSTATS_TOKEN", ""))
    if from_env and from_env != from_file:
        return from_env, "переменная окружения MPSTATS_TOKEN"
    if from_file:
        return from_file, f"файл {env_file}"
    return "", ""


def clean_token(value: str) -> str:
    """Токен без пробелов, кавычек и приставок, которые попадают при копировании."""
    value = clean_key(value).strip("\"'")
    for prefix in ("MPSTATS_TOKEN=", "X-Mpstats-TOKEN:", "Bearer"):
        if value.lower().startswith(prefix.lower()):
            value = value[len(prefix) :]
    return value.strip("\"'")


def describe(value: str, source: str) -> str:
    """Для сообщений об ошибке: откуда взят токен и его размер, сам токен не показывается."""
    return f"токен взят из: {source}; длина {len(value)} симв., точек {value.count('.')}, окончание …{value[-4:]}"


def token() -> str:
    if value := token_source()[0]:
        return value
    raise MpstatsError(
        f"Нет токена MPSTATS: добавьте строку MPSTATS_TOKEN=... в файл {BACKEND_DIR / '.env'} "
        "(это папка той копии Торпеды, которая сейчас запущена)"
    )


def get(client: httpx.Client, path: str, params: dict[str, Any] | None = None) -> Any:
    """GET с повтором на 202 (данные готовятся) и 429 (лимит запросов)."""
    for _ in range(5):
        resp = client.get(f"{BASE}/{path}", params=params)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (202, 429):
            time.sleep(min(int(resp.headers.get("Retry-After") or 5), 60))
            continue
        if resp.status_code == 401:
            value, source = token_source()
            raise MpstatsError(
                "MPSTATS не принял токен (401). Проверьте, что токен скопирован целиком из mpstats.io/userpanel "
                "(блок «API токен»; он меняется после смены пароля) и что тариф включает доступ к API. "
                f"Сейчас {describe(value, source)}. Ответ MPSTATS: {resp.text[:200]}"
            )
        raise MpstatsError(f"MPSTATS ответил {resp.status_code} на {path}: {resp.text[:300]}")
    raise MpstatsError(f"MPSTATS не отдал данные по {path} после нескольких попыток")


def pick(row: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if row.get(key) is not None:
            return row[key]
    return None


def num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def daily_rows(payload: Any) -> list[dict]:
    """Список строк по дням: ответ бывает списком или словарём со списком внутри."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list) and value and isinstance(value[0], dict) and pick(value[0], DATE_KEYS):
                return value
    return []


def summarize(sku: int, full: Any, by_period: Any) -> dict[str, Any]:
    rows = sorted(daily_rows(by_period), key=lambda r: str(pick(r, DATE_KEYS)))
    sales = [num(pick(r, SALES_KEYS)) or 0 for r in rows]
    prices = [p for r in rows if (p := num(pick(r, PRICE_KEYS)))]
    balances = [num(pick(r, BALANCE_KEYS)) for r in rows]
    revenue = sum(
        num(pick(r, REVENUE_KEYS)) or s * (num(pick(r, PRICE_KEYS)) or 0) for r, s in zip(rows, sales, strict=True)
    )
    info = full if isinstance(full, dict) else {}
    item = info.get("item") if isinstance(info.get("item"), dict) else info
    half = len(rows) // 2
    return {
        "sku": sku,
        "name": item.get("name") or item.get("title") or "",
        "days": len(rows),
        "period": f"{pick(rows[0], DATE_KEYS)} … {pick(rows[-1], DATE_KEYS)}" if rows else "",
        "sales": round(sum(sales)),
        "sales_first_half": round(sum(sales[:half])),
        "sales_second_half": round(sum(sales[half:])),
        "revenue": round(revenue),
        "price_first": prices[0] if prices else None,
        "price_last": prices[-1] if prices else None,
        "price_min": min(prices) if prices else None,
        "price_max": max(prices) if prices else None,
        "price_avg": round(sum(prices) / len(prices)) if prices else None,
        "base_price_last": num(pick(rows[-1], BASE_PRICE_KEYS)) if rows else None,
        "balance_last": balances[-1] if balances else None,
        "days_out_of_stock": sum(1 for b in balances if b == 0),
        "fields": sorted(rows[0]) if rows else [],
    }


def fetch(skus: list[int], d1: date, d2: date) -> list[dict[str, Any]]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    headers = {"X-Mpstats-TOKEN": token(), "Content-Type": "application/json"}
    params = {"d1": d1.isoformat(), "d2": d2.isoformat()}
    result = []
    with httpx.Client(headers=headers, timeout=60) as client:
        for sku in skus:
            full = get(client, f"items/{sku}/full", params)
            by_period = get(client, f"items/{sku}/by_period", params)
            raw = {"sku": sku, "d1": params["d1"], "d2": params["d2"], "full": full, "by_period": by_period}
            (OUT_DIR / f"{sku}_{params['d1']}_{params['d2']}.json").write_text(
                json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            result.append(summarize(sku, full, by_period))
    return result


def fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.0f}".replace(",", " ")
    return str(value)


def print_report(rows: list[dict[str, Any]]) -> None:
    for r in rows:
        print(f"\nАртикул {r['sku']}  {r['name']}")
        print(f"  Период: {r['period']} ({r['days']} дн.)")
        print(
            f"  Продажи: {r['sales']} шт. (первая половина {r['sales_first_half']}, "
            f"вторая {r['sales_second_half']}), выручка ≈ {fmt(float(r['revenue']))} ₽"
        )
        print(
            f"  Цена покупателя: было {fmt(r['price_first'])}, сейчас {fmt(r['price_last'])}, "
            f"мин {fmt(r['price_min'])}, макс {fmt(r['price_max'])}, средняя {fmt(r['price_avg'])} ₽"
        )
        print(f"  Цена до скидки сейчас: {fmt(r['base_price_last'])} ₽")
        print(f"  Остаток сейчас: {fmt(r['balance_last'])} шт., дней без остатка: {r['days_out_of_stock']}")
        if not r["days"]:
            print("  По дням данных нет: смотрите сохранённый ответ в папке ниже.")
    print(f"\nПолные ответы MPSTATS: {OUT_DIR}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Данные MPSTATS по артикулам WB")
    parser.add_argument("skus", nargs="*", type=int, default=list(DEFAULT_SKUS))
    parser.add_argument("--days", type=int, default=30, help="сколько последних дней (по умолчанию 30)")
    parser.add_argument("--json", action="store_true", help="напечатать сводку в JSON")
    args = parser.parse_args(argv)
    d2 = date.today() - timedelta(days=1)
    d1 = d2 - timedelta(days=args.days - 1)
    try:
        rows = fetch(args.skus, d1, d2)
    except (MpstatsError, httpx.HTTPError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        print_report(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
