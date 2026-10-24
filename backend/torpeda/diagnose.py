"""Диагностика «Что пошло не так»: живой запрос к WB и объяснение ответа простыми словами."""

from __future__ import annotations

import base64
import json
from datetime import datetime

from torpeda.wb_api.client import WBClient

STOCK_CHECKS = {
    "Остатки FBO (склады WB)": "wb",
    "Остатки FBS (склады продавца)": "seller",
}


def explain(status: int, body: str, rows: int | None) -> str:
    low = body.lower()
    if status == 0:
        return "Нет связи с сервером WB: проверьте интернет или VPN."
    if status in (200, 204) and rows:
        return f"Всё в порядке: WB отдал {rows} строк."
    if status in (200, 204):
        return "WB ответил без ошибки, но остатков нет: список пустой. Данные у WB обновляются раз в 30 минут."
    if status in (401, 403):
        if "additional requirements" in low:
            return (
                "WB пишет, что ключ не отвечает дополнительным требованиям этого метода "
                "(по документации метод принимает «Персональный» и «Сервисный» ключи). "
                "Торпеда всё равно загрузит остатки запасным способом: FBO — из отчёта об остатках "
                "(около минуты), FBS — через раздел ключа «Маркетплейс». "
                "Свойства ключа — в блоке выше: пришлите его скриншот."
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


# Расшифровка по документации WB (dev.wildberries.ru, «Информация об API» → структура токена)
TOKEN_TYPES = {1: "Базовый", 2: "Тестовый", 3: "Персональный", 4: "Сервисный"}
TOKEN_CATEGORIES = {1: "Контент", 2: "Аналитика", 3: "Цены и скидки", 4: "Маркетплейс", 5: "Статистика",
                    6: "Продвижение", 7: "Вопросы и отзывы", 9: "Чат с покупателями", 10: "Поставки",
                    11: "Возвраты покупателями", 12: "Документы", 13: "Финансы", 16: "Пользователи"}  # fmt: skip
READ_ONLY_BIT = 30

# Поля ключа, которые не показываем: это номера кабинета, пользователя и самого ключа.
HIDDEN_CLAIMS = {"id", "jti", "uid", "oid", "sid", "user", "seller"}


def token_info(token: str) -> dict:
    """Свойства ключа WB без самого ключа: WB-ключ — это JWT, его средняя часть читается без секрета.

    Показываем поля как есть и расшифровку словами; номера кабинета и пользователя скрываем."""
    parts = (token or "").split(".")
    if len(parts) != 3:
        return {"ok": False, "text": "Ключ не похож на ключ WB (ожидается три части через точку)."}
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except (ValueError, UnicodeDecodeError):
        return {"ok": False, "text": "Не получилось прочитать свойства ключа."}
    claims = {}
    for k, v in payload.items():
        if k.lower() in HIDDEN_CLAIMS:
            claims[k] = "скрыто"
        elif k in ("exp", "iat", "nbf") and isinstance(v, int | float):
            claims[k] = datetime.fromtimestamp(v).strftime("%d.%m.%Y %H:%M")
        elif k == "s" and isinstance(v, int):
            claims[k] = f"{v} (биты: {', '.join(str(i) for i in range(v.bit_length()) if v >> i & 1)})"
        else:
            claims[k] = v
    expired = isinstance(payload.get("exp"), int | float) and payload["exp"] < datetime.now().timestamp()
    kind = TOKEN_TYPES.get(payload.get("acc"), f"неизвестный (acc={payload.get('acc')})")
    s = payload.get("s") if isinstance(payload.get("s"), int) else 0
    summary = [f"Тип ключа: {kind}"]
    if "exp" in claims:
        summary.append(f"Действует до: {claims['exp']}" + (" — срок истёк" if expired else ""))
    cats = [name for bit, name in TOKEN_CATEGORIES.items() if s >> bit & 1]
    summary.append("Категории: " + (", ".join(cats) or "нет"))
    summary.append("Только чтение: " + ("да" if s >> READ_ONLY_BIT & 1 else "нет"))
    text = "Срок действия ключа истёк." if expired else ""
    if payload.get("acc") == 1:
        text = (
            "Это «Базовый» ключ. WB не пускает его к быстрому методу остатков, поэтому Торпеда берёт остатки "
            "запасным способом. Чтобы работало быстрее, создайте в кабинете WB ключ типа «Персональный»."
        )
    return {"ok": not expired and payload.get("acc") != 1, "text": text, "summary": summary, "claims": claims}
