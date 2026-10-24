"""Цена на сайте Wildberries: что видит покупатель в выбранном регионе.

Это не API продавца, а публичная карточка товара (card.wb.ru), которой пользуется сам сайт.
WB может в любой момент поменять её адрес или формат и не пускает обычные программы
(проверяет «отпечаток» соединения), поэтому запрос идёт через curl_cffi, который представляется браузером.
Цены в ответе — в копейках.
"""

from __future__ import annotations

from decimal import Decimal

from torpeda.wb_api.client import WBError

CARD_URL = "https://card.wb.ru/cards/v4/detail"
MOSCOW = -1257786  # регион «Москва» (параметр dest), как на сайте по умолчанию
BATCH = 100


def get_site_prices(nm_ids: list[int], dest: int = MOSCOW) -> dict[int, Decimal]:
    """{артикул: цена для покупателя, руб}. Товары, которых сейчас нельзя купить, в ответ не попадают."""
    try:
        from curl_cffi import requests
    except ImportError as e:  # pragma: no cover — библиотека ставится вместе с программой
        raise WBError("Не установлена библиотека curl_cffi. Запустите start.bat ещё раз.") from e
    out: dict[int, Decimal] = {}
    for i in range(0, len(nm_ids), BATCH):
        params = {"appType": 1, "curr": "rub", "dest": dest, "nm": ";".join(map(str, nm_ids[i : i + BATCH]))}
        try:
            resp = requests.get(CARD_URL, params=params, impersonate="chrome", timeout=20)
        except Exception as e:  # сеть, VPN, блокировка
            raise WBError(f"Сайт WB не ответил: {e}. Проверьте интернет или VPN.") from e
        if resp.status_code != 200:
            raise WBError(f"Сайт WB не отдал цены (код {resp.status_code}). Возможно, WB поменял страницу товара.")
        out.update(parse_card(resp.json()))
    return out


def parse_card(data: dict) -> dict[int, Decimal]:
    out = {}
    products = (data.get("data") or data).get("products") or []
    for p in products:
        for size in p.get("sizes") or []:
            kopecks = (size.get("price") or {}).get("product")
            if kopecks:
                out[p["id"]] = Decimal(kopecks) / 100
                break
    return out
