"""Диагностика «Что пошло не так»: живой запрос к WB и объяснение ответа простыми словами."""

from __future__ import annotations

import json

from torpeda.wb_api.client import WBClient

STOCK_CHECKS = {
    "Остатки FBO (склады WB)": "wb",
    "Остатки FBS (склады продавца)": "seller",
}


def explain(status: int, body: str, rows: int | None) -> str:
    low = body.lower()
    if status == 0:
        return "Нет связи с WB: проверьте интернет."
    if status in (200, 204) and rows:
        return f"Всё в порядке: WB отдал {rows} строк."
    if status in (200, 204):
        return "WB ответил без ошибки, но остатков нет: список пустой. Данные у WB обновляются раз в 30 минут."
    if status in (401, 403):
        if "additional requirements" in low:
            return (
                "У ключа тип «Базовый», а этот метод WB отдаёт только по «Персональному» ключу. "
                "Остатки FBO Торпеда всё равно загрузит запасным способом (медленнее, около минуты). "
                "Чтобы работало всё и быстро, создайте в кабинете WB ключ типа «Персональный» "
                "(Настройки → Доступ к API) с теми же категориями и вставьте его сюда."
            )
        if "type" in low or "тип" in low:
            return (
                "WB не принимает этот тип ключа. Для остатков нужен «Персональный» или «Сервисный» ключ "
                "(для FBO подходит и «Базовый с секретом»). Создайте ключ нужного типа с категорией «Аналитика»."
            )
        if "scope" in low or "categor" in low or "категор" in low:
            return "У ключа нет категории «Аналитика»."
        return f"WB отказал в доступе ({status}). Чаще всего это категория или тип ключа: смотрите ответ WB ниже."
    if status == 404:
        return "WB не знает такой адрес (404): похоже, метод снова поменялся. Пришлите скриншот."
    if status == 429:
        return "Слишком частые запросы (429). Подождите минуту и проверьте снова."
    if status >= 500:
        return f"Сбой на стороне WB ({status}). Попробуйте позже."
    return f"WB вернул код {status}. Смотрите ответ WB ниже."


def _rows(body: str) -> int | None:
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if isinstance(data, dict):
        items = (data.get("data") or {}).get("items") if isinstance(data.get("data"), dict) else None
        return len(items) if isinstance(items, list) else None
    return len(data) if isinstance(data, list) else None


def check_stocks(client: WBClient) -> list[dict]:
    out = []
    for title, kind in STOCK_CHECKS.items():
        url = client.stocks_url(kind)
        status, body = client.probe("POST", url, json={"limit": 10, "offset": 0})
        rows = _rows(body) if status == 200 else (0 if status == 204 else None)
        out.append(
            {
                "what": title,
                "request": f"POST {url}",
                "status": status,
                "rows": rows,
                "explanation": explain(status, body, rows),
                "answer": body[:600],
            }
        )
    return out
