"""Клиент API Wildberries.

Всё, кроме upload_prices/get_upload_task, только читает. Запись цен идёт отдельным
ключом с категорией «Цены и скидки» (WB_PRICES_TOKEN).

Методы и хосты по документации https://dev.wildberries.ru (категории токена в скобках):
- товары: content-api, POST /content/v2/get/cards/list                         (Контент)
- цены и скидки: discounts-prices-api, GET /api/v2/list/goods/filter          (Цены и скидки)
- комиссии по предметам: common-api, GET /api/v1/tariffs/commission           (любой токен)
- остатки FBO, заказы, продажи, финотчёт: statistics-api                       (Статистика)
- календарь акций и товары акции: dp-calendar-api                              (Цены и скидки)

Ответы WB возвращаются как есть (dict/list), разбор — в torpeda.sync.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from datetime import date, datetime
from typing import Any

import httpx

CONTENT = "https://content-api.wildberries.ru"
PRICES = "https://discounts-prices-api.wildberries.ru"
COMMON = "https://common-api.wildberries.ru"
STATISTICS = "https://statistics-api.wildberries.ru"
CALENDAR = "https://dp-calendar-api.wildberries.ru"

# Хост → категория токена, которую надо включить. Нужен для понятных сообщений при проверке связи.
PING_TARGETS = {
    "Контент": CONTENT,
    "Цены и скидки": PRICES,
    "Статистика": STATISTICS,
    "Тарифы": COMMON,
    "Календарь акций": CALENDAR,
}


class WBError(Exception):
    pass


class WBAuthError(WBError):
    """Токен не подходит: неверный, просрочен или без нужной категории."""


class WBClient:
    def __init__(
        self,
        token: str,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 5,
    ):
        if not token:
            raise WBAuthError("Не задан ключ WB. Положите его в файл backend/.env (см. docs/setup-api.md).")
        self._http = httpx.Client(headers={"Authorization": token}, timeout=60, transport=transport)
        self._sleep = sleep
        self._max_retries = max_retries

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> WBClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _request(self, method: str, url: str, **kwargs) -> Any:
        for attempt in range(self._max_retries + 1):
            resp = self._http.request(method, url, **kwargs)
            if resp.status_code == 429 and attempt < self._max_retries:
                # WB ограничивает частоту запросов; ждём, сколько он просит
                retry = resp.headers.get("X-Ratelimit-Retry") or resp.headers.get("Retry-After") or "60"
                self._sleep(float(retry))
                continue
            if resp.status_code in (401, 403):
                raise WBAuthError(f"WB отказал в доступе ({resp.status_code}) к {url}: {resp.text[:200]}")
            if resp.status_code >= 400:
                raise WBError(f"WB вернул {resp.status_code} на {url}: {resp.text[:200]}")
            if resp.status_code == 204 or not resp.content:
                return None
            return resp.json()
        raise WBError(f"WB слишком долго ограничивает запросы к {url}")

    # --- проверка связи ---

    def ping(self) -> dict[str, str]:
        """Проверяет каждый сервис WB. Возвращает {категория: 'ok' или текст ошибки}."""
        result = {}
        for name, host in PING_TARGETS.items():
            try:
                self._request("GET", f"{host}/ping")
                result[name] = "ok"
            except WBError as e:
                result[name] = str(e)
        return result

    # --- товары ---

    def iter_cards(self, page_size: int = 100) -> Iterator[dict]:
        cursor: dict[str, Any] = {"limit": page_size}
        while True:
            body = {"settings": {"cursor": cursor, "filter": {"withPhoto": -1}}}
            data = self._request("POST", f"{CONTENT}/content/v2/get/cards/list", json=body)
            cards = data.get("cards") or []
            yield from cards
            c = data.get("cursor") or {}
            if len(cards) < page_size or not c.get("nmID"):
                return
            cursor = {"limit": page_size, "updatedAt": c["updatedAt"], "nmID": c["nmID"]}

    # --- цены ---

    def iter_prices(self, page_size: int = 1000) -> Iterator[dict]:
        offset = 0
        while True:
            data = self._request(
                "GET", f"{PRICES}/api/v2/list/goods/filter", params={"limit": page_size, "offset": offset}
            )
            goods = ((data or {}).get("data") or {}).get("listGoods") or []
            yield from goods
            if len(goods) < page_size:
                return
            offset += page_size

    # --- комиссии ---

    def get_commissions(self) -> list[dict]:
        data = self._request("GET", f"{COMMON}/api/v1/tariffs/commission", params={"locale": "ru"})
        return (data or {}).get("report") or []

    # --- статистика ---

    def get_stocks(self, date_from: date) -> list[dict]:
        return (
            self._request("GET", f"{STATISTICS}/api/v1/supplier/stocks", params={"dateFrom": date_from.isoformat()})
            or []
        )

    def get_orders(self, date_from: date) -> list[dict]:
        return (
            self._request("GET", f"{STATISTICS}/api/v1/supplier/orders", params={"dateFrom": date_from.isoformat()})
            or []
        )

    def get_sales(self, date_from: date) -> list[dict]:
        return (
            self._request("GET", f"{STATISTICS}/api/v1/supplier/sales", params={"dateFrom": date_from.isoformat()})
            or []
        )

    def iter_report_detail(self, date_from: date, date_to: date, page_size: int = 100_000) -> Iterator[dict]:
        """Детализация финансовых отчётов. Постранично по rrd_id."""
        rrdid = 0
        while True:
            rows = self._request(
                "GET",
                f"{STATISTICS}/api/v5/supplier/reportDetailByPeriod",
                params={
                    "dateFrom": date_from.isoformat(),
                    "dateTo": date_to.isoformat(),
                    "limit": page_size,
                    "rrdid": rrdid,
                },
            )
            if not rows:
                return
            yield from rows
            if len(rows) < page_size:
                return
            rrdid = rows[-1]["rrd_id"]

    # --- акции ---

    def get_promotions(self, start: datetime, end: datetime) -> list[dict]:
        data = self._request(
            "GET",
            f"{CALENDAR}/api/v1/calendar/promotions",
            params={
                "startDateTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "endDateTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "allPromo": "true",
                "limit": 1000,
            },
        )
        return ((data or {}).get("data") or {}).get("promotions") or []

    def iter_promotion_items(self, promotion_id: int, page_size: int = 1000) -> Iterator[dict]:
        """Товары акции: и участвующие, и те, что можно добавить."""
        for in_action in ("true", "false"):
            offset = 0
            while True:
                data = self._request(
                    "GET",
                    f"{CALENDAR}/api/v1/calendar/promotions/nomenclatures",
                    params={"promotionID": promotion_id, "inAction": in_action, "limit": page_size, "offset": offset},
                )
                items = ((data or {}).get("data") or {}).get("nomenclatures") or []
                yield from items
                if len(items) < page_size:
                    break
                offset += page_size

    # --- запись цен (ключ WB_PRICES_TOKEN) ---

    def upload_prices(self, items: list[dict]) -> int:
        """Отправляет цены и скидки. items: [{"nmID": int, "price": int, "discount": int}]. Возвращает id задачи WB."""
        data = self._request("POST", f"{PRICES}/api/v2/upload/task", json={"data": items})
        if (data or {}).get("error"):
            raise WBError(f"WB не принял цены: {data.get('errorText')}")
        return data["data"]["id"]

    def get_upload_task(self, task_id: int) -> dict:
        """Статус обработанной задачи загрузки цен."""
        data = self._request("GET", f"{PRICES}/api/v2/history/tasks", params={"uploadID": task_id})
        return (data or {}).get("data") or {}
