"""Реклама (этап 4): статистика кампаний по товарам и списания.

Затраты по товарам — из статистики кампаний (WB делит затраты кампании по товарам).
Списания — сколько WB фактически снял за рекламу и с какого счёта.
ДРР — доля рекламных расходов: затраты / сумма заказов с рекламы.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from torpeda.db import DEFAULT_ACCOUNT_ID
from torpeda.db.models import AdCost, AdStat, Product

from . import Column, Table

ACC = DEFAULT_ACCOUNT_ID
ZERO = Decimal(0)
FIELDS = ("views", "clicks", "atbs", "orders", "shks", "spend", "orders_sum")
ADVERT_TYPES = {4: "В каталоге", 5: "В карточке", 6: "В поиске", 7: "В рекомендациях", 8: "Автоматическая",
                9: "Аукцион"}  # fmt: skip


def _q(v: Decimal | None, places: str = "0.01") -> Decimal | None:
    return v.quantize(Decimal(places)) if v is not None else None


def _derived(r: dict) -> dict:
    views, clicks, spend = r["views"], r["clicks"], r["spend"]
    return r | {
        "ctr": _q(Decimal(clicks) * 100 / views) if views else None,
        "cpc": _q(spend / clicks) if clicks else None,
        "cpm": _q(spend * 1000 / views) if views else None,
        "cr": _q(Decimal(r["orders"]) * 100 / clicks) if clicks else None,
        "cpo": _q(spend / r["orders"]) if r["orders"] else None,
        "drr": _q(spend * 100 / r["orders_sum"]) if r["orders_sum"] else None,
    }


def ad_spend_by_nm(s: Session, date_from: date, date_to: date) -> dict[int, Decimal]:
    """Затраты на рекламу по товарам за даты — для маржи в детализации."""
    out: dict[int, Decimal] = defaultdict(lambda: ZERO)
    q = select(AdStat).where(AdStat.account_id == ACC, AdStat.date >= date_from, AdStat.date <= date_to)
    for x in s.scalars(q):
        out[x.nm_id] += x.spend or ZERO
    return dict(out)


def _campaigns(s: Session) -> dict[int, tuple[str | None, int | None]]:
    out = {}
    for c in s.scalars(select(AdCost).where(AdCost.account_id == ACC).order_by(AdCost.at)):
        out[c.advert_id] = (c.campaign, c.advert_type)
    return out


def ads(s: Session, date_from: date, date_to: date, group: str = "nm") -> Table:
    group = group if group in ("nm", "campaign", "day") else "nm"
    q = select(AdStat).where(AdStat.account_id == ACC, AdStat.date >= date_from, AdStat.date <= date_to)
    data: dict = defaultdict(lambda: dict.fromkeys(FIELDS, 0))
    total = dict.fromkeys(FIELDS, 0)
    for x in s.scalars(q):
        key = {"nm": x.nm_id, "campaign": x.advert_id, "day": x.date}[group]
        for f in FIELDS:
            v = getattr(x, f) or 0
            data[key][f] += v
            total[f] += v
    products = {p.nm_id: p for p in s.scalars(select(Product).where(Product.account_id == ACC))}
    camps = _campaigns(s)
    rows = []
    for key, a in data.items():
        r = _derived(dict(a))
        if group == "nm":
            p = products.get(key)
            r |= {"nm_id": key, "sa_name": p.vendor_code if p else None, "subject": p.subject_name if p else None}
        elif group == "campaign":
            name, kind = camps.get(key, (None, None))
            r |= {"advert_id": key, "campaign": name, "type": ADVERT_TYPES.get(kind, kind)}
        else:
            r["day"] = key
        rows.append(r)
    rows.sort(key=(lambda r: r["day"]) if group == "day" else (lambda r: r["spend"]), reverse=group != "day")

    head = {
        "nm": [
            Column("nm_id", "Артикул WB", "text"),
            Column("sa_name", "Артикул продавца", "text"),
            Column("subject", "Предмет", "text"),
        ],
        "campaign": [
            Column("advert_id", "Кампания", "text"),
            Column("campaign", "Название", "text"),
            Column("type", "Тип", "text"),
        ],
        "day": [Column("day", "Дата", "date")],
    }[group]
    columns = head + [
        Column("views", "Показы", "int"),
        Column("clicks", "Клики", "int"),
        Column("ctr", "CTR, %", "pct"),
        Column("cpc", "Цена клика, руб"),
        Column("cpm", "Цена 1000 показов, руб"),
        Column("atbs", "В корзину, шт", "int"),
        Column("orders", "Заказы, шт", "int"),
        Column("cr", "Конверсия клик → заказ, %", "pct"),
        Column("spend", "Затраты, руб"),
        Column("cpo", "Цена заказа, руб"),
        Column("orders_sum", "Заказы с рекламы, руб"),
        Column("drr", "ДРР, %", "pct"),
    ]
    totals = _derived(total) | {columns[0].field: "Итого"}
    notes = [
        "Данные из статистики кампаний WB. ДРР — затраты к сумме заказов с рекламы.",
        "Загружается кнопкой «Загрузить рекламу из WB за эти даты». Нужна категория ключа «Продвижение».",
    ]
    titles = {"nm": "по артикулам", "campaign": "по кампаниям", "day": "по дням"}
    return Table(f"Реклама {titles[group]}", columns, rows, totals, notes)


def ad_costs(s: Session, date_from: date, date_to: date) -> Table:
    q = select(AdCost).where(
        AdCost.account_id == ACC,
        AdCost.at >= datetime.combine(date_from, datetime.min.time()),
        AdCost.at < datetime.combine(date_to + timedelta(days=1), datetime.min.time()),
    )
    data: dict = defaultdict(lambda: {"amount": ZERO, "count": 0})
    names: dict[int, tuple] = {}
    for c in s.scalars(q):
        key = (c.advert_id, c.payment_type or "—")
        data[key]["amount"] += c.amount or ZERO
        data[key]["count"] += 1
        names[c.advert_id] = (c.campaign, c.advert_type)
    rows = []
    for (advert_id, pay), a in data.items():
        name, kind = names.get(advert_id, (None, None))
        rows.append({"advert_id": advert_id, "campaign": name, "type": ADVERT_TYPES.get(kind, kind),
                     "payment_type": pay, "count": a["count"], "amount": a["amount"]})  # fmt: skip
    rows.sort(key=lambda r: r["amount"], reverse=True)
    columns = [
        Column("advert_id", "Кампания", "text"),
        Column("campaign", "Название", "text"),
        Column("type", "Тип", "text"),
        Column("payment_type", "Откуда списано", "text"),
        Column("count", "Списаний", "int"),
        Column("amount", "Списано, руб"),
    ]
    totals = {
        "advert_id": "Итого",
        "count": sum(r["count"] for r in rows),
        "amount": sum((r["amount"] for r in rows), ZERO),
    }
    notes = ["Фактические списания WB за рекламу. Они могут не совпадать с затратами в статистике по дням."]
    return Table("Списания за рекламу", columns, rows, totals, notes)


REPORTS = {"ads": ads, "ad_costs": ad_costs}

__all__ = ["REPORTS", "ad_spend_by_nm"]
