"""Клиент API Wildberries.

Всё, кроме upload_prices/get_upload_task, только читает. Запись цен идёт отдельным
ключом с категорией «Цены и скидки» (WB_PRICES_TOKEN).

Методы и хосты по документации https://dev.wildberries.ru (категории токена в скобках):
- товары: content-api, POST /content/v2/get/cards/list                         (Контент)
- цены и скидки: discounts-prices-api, GET /api/v2/list/goods/filter          (Цены и скидки)
- комиссии по предметам: common-api, GET /api/v1/tariffs/commission           (любой токен)
- заказы, продажи, финотчёт: statistics-api                                    (Статистика)
- остатки на складах WB (FBO) и продавца (FBS): seller-analytics-api,
  POST /api/analytics/v1/stocks-report/wb-warehouses и /seller-warehouses     (Аналитика)
  (старый GET /api/v1/supplier/stocks в statistics-api WB отключил)
- финотчёты: finance-api, POST /api/finance/v1/sales-reports/detailed и /list     (Финансы),
  запасной способ — statistics-api reportDetailByPeriod                         (Статистика)
- воронка продаж: seller-analytics-api, POST /api/analytics/v3/sales-funnel/products  (Аналитика)
- платное хранение и приёмка: seller-analytics-api, отчёты-задания
  /api/v1/paid_storage и /api/v1/acceptance_report                             (Аналитика)
- реклама: advert-api, списки кампаний /adv/v1/promotion/count, статистика /adv/v3/fullstats,
  история затрат /adv/v1/upd                                                     (Продвижение)
- коэффициенты приёмки: common-api /api/tariffs/v1/acceptance/coefficients      (Тарифы),
  запасной способ — supplies-api /api/v1/acceptance/coefficients                 (Поставки)
- календарь акций и товары акции: dp-calendar-api                              (Цены и скидки)

Ответы WB возвращаются как есть (dict/list), разбор — в torpeda.sync.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from typing import Any

import httpx

CONTENT = "https://content-api.wildberries.ru"
PRICES = "https://discounts-prices-api.wildberries.ru"
COMMON = "https://common-api.wildberries.ru"
STATISTICS = "https://statistics-api.wildberries.ru"
CALENDAR = "https://dp-calendar-api.wildberries.ru"
ANALYTICS = "https://seller-analytics-api.wildberries.ru"
FINANCE = "https://finance-api.wildberries.ru"
ADVERT = "https://advert-api.wildberries.ru"
SUPPLIES = "https://supplies-api.wildberries.ru"
MARKETPLACE = "https://marketplace-api.wildberries.ru"

# Новый API финотчётов (finance-api) отдаёт поля в camelCase; приводим к именам старого
# reportDetailByPeriod, чтобы разбор в torpeda.sync был один для обоих источников.
FINANCE_FIELDS = {
    "reportId": "realizationreport_id",
    "dateFrom": "date_from",
    "dateTo": "date_to",
    "rrdId": "rrd_id",
    "nmId": "nm_id",
    "rrDate": "rr_dt",
    "vendorCode": "sa_name",
    "techSize": "ts_name",
    "subjectName": "subject_name",
    "brandName": "brand_name",
    "bonusTypeName": "bonus_type_name",
    "docTypeName": "doc_type_name",
    "sellerOperName": "supplier_oper_name",
    "officeName": "office_name",
    "quantity": "quantity",
    "retailPriceWithDisc": "retail_price_withdisc_rub",
    "retailAmount": "retail_amount",
    "forPay": "ppvz_for_pay",
    "deliveryService": "delivery_rub",
    "deliveryAmount": "delivery_amount",
    "returnAmount": "return_amount",
    "paidStorage": "storage_fee",
    "penalty": "penalty",
    "paidAcceptance": "acceptance",
    "deduction": "deduction",
    "acquiringFee": "acquiring_fee",
    "additionalPayment": "additional_payment",
    "rebillLogisticCost": "rebill_logistic_cost",
    "cashbackAmount": "cashback_amount",
    "cashbackDiscount": "cashback_discount",
    "cashbackCommissionChange": "cashback_commission_change",
    "srid": "srid",
}


def finance_row(r: dict) -> dict:
    """Строка finance-api с именами полей reportDetailByPeriod (остальные поля — как пришли)."""
    return {**r, **{old: r[new] for new, old in FINANCE_FIELDS.items() if new in r}}

# Хост → категория токена, которую надо включить. Нужен для понятных сообщений при проверке связи.
PING_TARGETS = {
    "Контент": CONTENT,
    "Цены и скидки": PRICES,
    "Статистика": STATISTICS,
    "Тарифы": COMMON,
    "Календарь акций": CALENDAR,
    "Аналитика": ANALYTICS,
    "Финансы": FINANCE,
    "Продвижение": ADVERT,
    "Маркетплейс (остатки FBS)": MARKETPLACE,
}


class WBError(Exception):
    pass


BASE_TOKEN_HINT = (
    "WB пишет, что ключ не отвечает дополнительным требованиям этого метода "
    "(по документации WB метод принимает «Персональный» и «Сервисный» ключи). "
    "Свойства ключа видны в «Настройках» → «Проверить остатки»."
)


NO_NETWORK_HINT = "Нет связи с сервером WB: проверьте интернет или VPN и повторите загрузку."
NETWORK_RETRY_WAITS = (2, 5, 10)


def is_token_type_error(text: str) -> bool:
    """WB отвечает «token does not satisfy additional requirements», когда метод не принимает такой тип ключа."""
    return "additional requirements" in text.lower()


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
            raise WBAuthError("Не задан ключ WB. Вставьте его на вкладке «Настройки».")
        self._http = httpx.Client(headers={"Authorization": token}, timeout=60, transport=transport)
        self._sleep = sleep
        self._max_retries = max_retries

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> WBClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _send(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Запрос с повтором, если не удалось соединиться. Такой запрос до WB не дошёл, повторять безопасно."""
        for wait in NETWORK_RETRY_WAITS:
            try:
                return self._http.request(method, url, **kwargs)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                self._sleep(wait)
        try:
            return self._http.request(method, url, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            host = httpx.URL(url).host
            raise WBError(f"{NO_NETWORK_HINT} Сервер: {host}. Подробно: {type(e).__name__}: {e}") from e

    def _request(self, method: str, url: str, **kwargs) -> Any:
        for attempt in range(self._max_retries + 1):
            resp = self._send(method, url, **kwargs)
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

    def probe(self, method: str, url: str, **kwargs) -> tuple[int, str]:
        """Один запрос без повторов и без исключений: код ответа и текст. Для диагностики."""
        try:
            resp = self._http.request(method, url, **kwargs)
        except httpx.HTTPError as e:
            return 0, f"нет связи: {e}"
        return resp.status_code, resp.text

    def stocks_url(self, warehouses: str) -> str:
        return f"{ANALYTICS}/api/analytics/v1/stocks-report/{warehouses}-warehouses"

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

    def iter_stocks(self, warehouses: str, page_size: int = 250_000) -> Iterator[dict]:
        """Текущие остатки по размерам: warehouses="wb" — склады WB (FBO), "seller" — склады продавца (FBS)."""
        offset = 0
        while True:
            data = self._request(
                "POST",
                self.stocks_url(warehouses),
                json={"limit": page_size, "offset": offset},
            )
            items = ((data or {}).get("data") or {}).get("items") or []
            yield from items
            if len(items) < page_size:
                return
            offset += page_size

    def get_seller_warehouses(self) -> list[dict]:
        """Склады продавца (FBS). Нужна категория ключа «Маркетплейс»."""
        return self._request("GET", f"{MARKETPLACE}/api/v3/warehouses") or []

    def get_seller_stocks(self, warehouse_id: int, chrt_ids: list[int]) -> list[dict]:
        """Остатки на складе продавца по размерам (chrtId), не больше 1000 размеров за запрос."""
        out = []
        for i in range(0, len(chrt_ids), 1000):
            data = self._request(
                "POST", f"{MARKETPLACE}/api/v3/stocks/{warehouse_id}", json={"chrtIds": chrt_ids[i : i + 1000]}
            )
            out += (data or {}).get("stocks") or []
        return out

    def get_warehouse_remains(self) -> list[dict]:
        """Остатки на складах WB через отчёт-задание: работает и с «Базовым» ключом, но медленнее.
        У «Базового» ключа проверка готовности — раз в 15 минут, поэтому сначала даём отчёту 30 секунд."""
        params = {"groupByNm": "true", "groupBySize": "true", "groupBySa": "true"}
        return self._task_report("warehouse_remains", params=params, first_wait=30)

    def get_orders(self, date_from: date) -> list[dict]:
        return self._statistics_changes("orders", date_from)

    def get_sales(self, date_from: date) -> list[dict]:
        return self._statistics_changes("sales", date_from)

    def _statistics_changes(self, kind: str, date_from: date, page_size: int = 80_000) -> list[dict]:
        """Заказы или продажи, изменённые с даты. WB отдаёт до 80 000 строк за раз; следующую порцию
        просим с lastChangeDate последней строки."""
        out: list[dict] = []
        since = date_from.isoformat()
        while True:
            page = self._request("GET", f"{STATISTICS}/api/v1/supplier/{kind}", params={"dateFrom": since}) or []
            out.extend(page)
            if len(page) < page_size or not page[-1].get("lastChangeDate"):
                return out
            since = page[-1]["lastChangeDate"]

    def iter_report_detail(self, date_from: date, date_to: date, page_size: int = 100_000) -> Iterator[dict]:
        """Детализация еженедельных финотчётов, постранично по rrd_id.

        Сначала новый finance-api (категория «Финансы»). Если у ключа нет этой категории
        или метод недоступен — старый statistics-api reportDetailByPeriod (категория «Статистика»).
        """
        try:
            first = self._finance_detail_page(date_from, date_to, 0, page_size)
        except WBError as finance_error:
            try:
                yield from self._iter_statistics_detail(date_from, date_to, page_size)
            except WBError as e:
                raise WBError(f"{finance_error} | запасной способ: {e}") from e
            return
        page = first
        while page:
            yield from page
            if len(page) < page_size:
                return
            page = self._finance_detail_page(date_from, date_to, page[-1]["rrd_id"], page_size)

    def _finance_detail_page(self, date_from: date, date_to: date, rrd_id: int, limit: int) -> list[dict]:
        rows = self._request(
            "POST",
            f"{FINANCE}/api/finance/v1/sales-reports/detailed",
            json={
                "dateFrom": date_from.isoformat(),
                "dateTo": date_to.isoformat(),
                "limit": limit,
                "rrdId": rrd_id,
                "period": "weekly",
            },
        )
        return [finance_row(r) for r in rows or []]

    def _iter_statistics_detail(self, date_from: date, date_to: date, page_size: int) -> Iterator[dict]:
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

    def get_sales_reports(self, date_from: date, date_to: date) -> list[dict]:
        """Список еженедельных отчётов реализации с итогами из шапки (finance-api)."""
        out: list[dict] = []
        offset = 0
        while True:
            page = self._request(
                "POST",
                f"{FINANCE}/api/finance/v1/sales-reports/list",
                json={
                    "dateFrom": date_from.isoformat(),
                    "dateTo": date_to.isoformat(),
                    "limit": 1000,
                    "offset": offset,
                    "period": "weekly",
                },
            )
            out.extend(page or [])
            if not page or len(page) < 1000:
                return out
            offset += 1000

    # --- аналитика: воронка, платное хранение, приёмка ---

    def iter_funnel(self, date_from: date, date_to: date, page_size: int = 1000) -> Iterator[dict]:
        """Воронка по карточкам за период (не старше года): {"product": {...}, "statistic": {"selected": {...}}}."""
        offset = 0
        while True:
            data = self._request(
                "POST",
                f"{ANALYTICS}/api/analytics/v3/sales-funnel/products",
                json={
                    "selectedPeriod": {"start": date_from.isoformat(), "end": date_to.isoformat()},
                    "nmIds": [],
                    "brandNames": [],
                    "subjectIds": [],
                    "tagIds": [],
                    "skipDeletedNm": False,
                    "limit": page_size,
                    "offset": offset,
                },
            )
            items = ((data or {}).get("data") or {}).get("products") or []
            yield from items
            if len(items) < page_size:
                return
            offset += page_size

    def _task_report(
        self,
        kind: str,
        date_from: date | None = None,
        date_to: date | None = None,
        poll: float = 5,
        max_wait: float = 600,
        params: dict | None = None,
        first_wait: float = 0,
    ) -> list:
        """Отчёт-задание WB: создать, дождаться готовности, скачать."""
        base = f"{ANALYTICS}/api/v1/{kind}"
        if params is None:
            params = {"dateFrom": date_from.isoformat(), "dateTo": date_to.isoformat()}
        created = self._request("GET", base, params=params)
        task = ((created or {}).get("data") or {}).get("taskId")
        if not task:
            raise WBError(f"WB не создал отчёт {kind}: {str(created)[:200]}")
        if first_wait:
            self._sleep(first_wait)
        waited = 0.0
        while True:
            status = (((self._request("GET", f"{base}/tasks/{task}/status") or {}).get("data")) or {}).get("status")
            if status == "done":
                return self._request("GET", f"{base}/tasks/{task}/download") or []
            if status in ("purged", "canceled"):
                raise WBError(f"WB отменил отчёт {kind} (статус {status})")
            if waited >= max_wait:
                raise WBError(f"WB слишком долго готовит отчёт {kind}, попробуйте позже")
            self._sleep(poll)
            waited += poll

    def _chunked(self, kind: str, date_from: date, date_to: date, days: int) -> Iterator[tuple[date, date, list]]:
        start = date_from
        while start <= date_to:
            end = min(start + timedelta(days=days - 1), date_to)
            yield start, end, self._task_report(kind, start, end)
            start = end + timedelta(days=1)

    def iter_paid_storage(self, date_from: date, date_to: date) -> Iterator[tuple[date, date, list]]:
        """Платное хранение по дням. WB отдаёт не больше 8 дней за раз, отчёт — раз в минуту."""
        return self._chunked("paid_storage", date_from, date_to, 8)

    def iter_acceptance(self, date_from: date, date_to: date) -> Iterator[tuple[date, date, list]]:
        """Платная приёмка. Не больше 31 дня за раз."""
        return self._chunked("acceptance_report", date_from, date_to, 31)

    # --- поставки ---

    def get_acceptance_coefficients(self) -> list[dict]:
        """Коэффициенты приёмки на 14 дней по всем складам. WB перенёс метод в «Тарифы»; старый адрес —
        запасной вариант для ключей с категорией «Поставки»."""
        try:
            return self._request("GET", f"{COMMON}/api/tariffs/v1/acceptance/coefficients") or []
        except WBError as first:
            try:
                return self._request("GET", f"{SUPPLIES}/api/v1/acceptance/coefficients") or []
            except WBError as e:
                raise type(e)(f"{first} | запасной способ: {e}") from e

    # --- реклама ---

    def get_advert_ids(self, changed_since: date) -> list[int]:
        """Кампании, у которых может быть статистика за период: идут (9), на паузе (11) и завершённые (7)
        не раньше начала периода."""
        data = self._request("GET", f"{ADVERT}/adv/v1/promotion/count") or {}
        ids = []
        for group in data.get("adverts") or []:
            if group.get("status") not in (7, 9, 11):
                continue
            for a in group.get("advert_list") or []:
                changed = (a.get("changeTime") or "")[:10]
                if group["status"] != 7 or not changed or changed >= changed_since.isoformat():
                    ids.append(a["advertId"])
        return ids

    def iter_ad_fullstats(self, ids: list[int], date_from: date, date_to: date) -> Iterator[dict]:
        """Статистика кампаний: до 50 кампаний и до 31 дня за запрос, 3 запроса в минуту."""
        for i in range(0, len(ids), 50):
            start = date_from
            while start <= date_to:
                end = min(start + timedelta(days=30), date_to)
                params = {
                    "ids": ",".join(map(str, ids[i : i + 50])),
                    "beginDate": start.isoformat(),
                    "endDate": end.isoformat(),
                }
                yield from self._request("GET", f"{ADVERT}/adv/v3/fullstats", params=params) or []
                start = end + timedelta(days=1)

    def iter_ad_costs(self, date_from: date, date_to: date) -> Iterator[dict]:
        """История списаний за рекламу, по 31 дню за запрос."""
        start = date_from
        while start <= date_to:
            end = min(start + timedelta(days=30), date_to)
            params = {"from": start.isoformat(), "to": end.isoformat()}
            yield from self._request("GET", f"{ADVERT}/adv/v1/upd", params=params) or []
            start = end + timedelta(days=1)

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
