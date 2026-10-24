"""Воронка продаж, платное хранение и платная приёмка (этап 4).

Воронку WB считает сам за весь период, поэтому она хранится ровно за те даты, за которые загружена.
Хранение и приёмка хранятся по дням и складываются за любые даты.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from torpeda.db import DEFAULT_ACCOUNT_ID
from torpeda.db.models import AcceptanceRow, FunnelRow, Product, StorageRow

from . import Column, Table

ACC = DEFAULT_ACCOUNT_ID
ZERO = Decimal(0)

NM_COLUMNS = [
    Column("nm_id", "Артикул WB", "text"),
    Column("sa_name", "Артикул продавца", "text"),
    Column("subject", "Предмет", "text"),
]


def _titles(s: Session) -> dict[int, tuple[str | None, str | None]]:
    return {
        p.nm_id: (p.vendor_code, p.subject_name) for p in s.scalars(select(Product).where(Product.account_id == ACC))
    }


def _pct(a, b) -> Decimal | None:
    return (Decimal(a) * 100 / Decimal(b)).quantize(Decimal("0.1")) if b else None


def _nm(nm: int, titles: dict) -> dict:
    sa, subject = titles.get(nm, (None, None))
    return {"nm_id": nm, "sa_name": sa, "subject": subject}


# --- воронка ---

FUNNEL_SUM = ("open_count", "cart_count", "wishlist", "order_count", "order_sum", "buyout_count", "buyout_sum",
              "cancel_count", "cancel_sum")  # fmt: skip


def _conversions(r: dict) -> dict:
    return r | {
        "cart_pct": _pct(r["cart_count"], r["open_count"]),
        "order_pct": _pct(r["order_count"], r["cart_count"]),
        "buyout_pct": _pct(r["buyout_count"], r["buyout_count"] + r["cancel_count"]),
    }


def funnel(s: Session, date_from: date, date_to: date) -> Table:
    rows_db = list(
        s.scalars(
            select(FunnelRow).where(
                FunnelRow.account_id == ACC, FunnelRow.date_from == date_from, FunnelRow.date_to == date_to
            )
        )
    )
    titles = _titles(s)
    rows = []
    total = dict.fromkeys(FUNNEL_SUM, 0)
    for f in rows_db:
        r = _nm(f.nm_id, titles) | {k: getattr(f, k) for k in FUNNEL_SUM}
        for k in FUNNEL_SUM:
            total[k] += r[k]
        rows.append(_conversions(r))
    rows.sort(key=lambda r: r["open_count"], reverse=True)
    columns = NM_COLUMNS + [
        Column("open_count", "Переходы в карточку", "int"),
        Column("cart_count", "В корзину, шт", "int"),
        Column("cart_pct", "Конверсия в корзину, %", "pct"),
        Column("wishlist", "В отложенные, шт", "int"),
        Column("order_count", "Заказы, шт", "int"),
        Column("order_pct", "Конверсия в заказ, %", "pct"),
        Column("order_sum", "Заказы, руб"),
        Column("buyout_count", "Выкупы, шт", "int"),
        Column("buyout_sum", "Выкупы, руб"),
        Column("cancel_count", "Отмены и возвраты, шт", "int"),
        Column("cancel_sum", "Отмены и возвраты, руб"),
        Column("buyout_pct", "Процент выкупа, %", "pct"),
    ]
    notes = ["Воронку считает WB. Выкупы и отмены — по заказам этих дат, часть ещё может быть в пути."]
    if not rows_db:
        notes.insert(0, "Воронки за эти даты нет. Нажмите «Загрузить воронку из WB за эти даты» (не старше года).")
    else:
        notes.insert(0, f"Загружено {max(f.loaded_at for f in rows_db):%d.%m.%Y %H:%M}.")
    totals = _conversions(total) | {"nm_id": "Итого"}
    return Table("Воронка продаж", columns, rows, totals, notes)


# --- платное хранение ---


def storage(s: Session, date_from: date, date_to: date, group: str = "nm") -> Table:
    group = group if group in ("nm", "warehouse", "day") else "nm"
    q = select(StorageRow).where(StorageRow.account_id == ACC, StorageRow.date >= date_from, StorageRow.date <= date_to)
    days = (date_to - date_from).days + 1
    data: dict = defaultdict(lambda: {"price": ZERO, "units": 0, "volume": ZERO, "nms": set(), "days": set()})
    for x in s.scalars(q):
        key = {"nm": x.nm_id, "warehouse": x.warehouse or "—", "day": x.date}[group]
        a = data[key]
        a["price"] += x.price or ZERO
        a["units"] += x.barcodes_count or 0
        a["volume"] += (x.volume or ZERO) * (x.barcodes_count or 0)
        a["nms"].add(x.nm_id)
        a["days"].add(x.date)
    titles = _titles(s)
    rows = []
    for key, a in data.items():
        n_days = len(a["days"]) or 1
        r = {
            "price": a["price"],
            "per_day": (a["price"] / n_days).quantize(Decimal("0.01")),
            "units": round(a["units"] / n_days),  # среднее количество на хранении в день
            "volume": (a["volume"] / n_days).quantize(Decimal("0.1")),
        }
        if group == "nm":
            r |= _nm(key, titles)
            r["per_unit"] = (a["price"] / a["units"]).quantize(Decimal("0.01")) if a["units"] else None
        elif group == "warehouse":
            r |= {"warehouse": key, "nm_count": len(a["nms"])}
        else:
            r |= {"day": key, "nm_count": len(a["nms"])}
        rows.append(r)
    if group == "day":
        rows.sort(key=lambda r: r["day"])
    else:
        rows.sort(key=lambda r: r["price"], reverse=True)

    head = {
        "nm": NM_COLUMNS,
        "warehouse": [Column("warehouse", "Склад", "text"), Column("nm_count", "Артикулов", "int")],
        "day": [Column("day", "Дата", "date"), Column("nm_count", "Артикулов", "int")],
    }[group]
    columns = head + [
        Column("price", "Хранение, руб"),
        Column("per_day", "В среднем за день, руб"),
        Column("units", "На хранении в день, шт", "int"),
        Column("volume", "Объём в день, л", "num"),
    ]
    if group == "nm":
        columns.append(Column("per_unit", "За 1 шт в день, руб"))
    total_price = sum((r["price"] for r in rows), ZERO)
    first = columns[0].field
    totals = {first: "Итого", "price": total_price, "per_day": (total_price / days).quantize(Decimal("0.01"))}
    notes = ["Платное хранение по данным WB, по дням. Загружается кнопкой «Загрузить хранение и приёмку из WB»."]
    if not rows:
        notes.insert(0, "За эти даты данных нет.")
    titles_ = {"nm": "по артикулам", "warehouse": "по складам", "day": "по дням"}
    return Table(f"Платное хранение {titles_[group]}", columns, rows, totals, notes)


# --- платная приёмка ---


def acceptance(s: Session, date_from: date, date_to: date, group: str = "nm") -> Table:
    group = group if group in ("nm", "income") else "nm"
    q = select(AcceptanceRow).where(
        AcceptanceRow.account_id == ACC, AcceptanceRow.date >= date_from, AcceptanceRow.date <= date_to
    )
    data: dict = defaultdict(lambda: {"count": 0, "total": ZERO, "nms": set(), "date": None})
    for x in s.scalars(q):
        key = x.nm_id if group == "nm" else x.income_id
        a = data[key]
        a["count"] += x.count or 0
        a["total"] += x.total or ZERO
        a["nms"].add(x.nm_id)
        a["date"] = max(filter(None, (a["date"], x.date)))
    titles = _titles(s)
    rows = []
    for key, a in data.items():
        r = {"count": a["count"], "total": a["total"]}
        r["per_unit"] = (a["total"] / a["count"]).quantize(Decimal("0.01")) if a["count"] else None
        if group == "nm":
            r |= _nm(key, titles)
        else:
            r |= {"income_id": key, "date": a["date"], "nm_count": len(a["nms"])}
        rows.append(r)
    rows.sort(key=lambda r: r["total"], reverse=True)
    head = (
        NM_COLUMNS
        if group == "nm"
        else [
            Column("income_id", "Поставка", "text"),
            Column("date", "Дата приёмки", "date"),
            Column("nm_count", "Артикулов", "int"),
        ]
    )
    columns = head + [
        Column("count", "Принято, шт", "int"),
        Column("total", "Приёмка, руб"),
        Column("per_unit", "За 1 шт, руб"),
    ]
    totals = {
        columns[0].field: "Итого",
        "count": sum(r["count"] for r in rows),
        "total": sum((r["total"] for r in rows), ZERO),
    }
    notes = [] if rows else ["За эти даты данных нет. Нажмите «Загрузить хранение и приёмку из WB»."]
    title = "Платная приёмка " + ("по артикулам" if group == "nm" else "по поставкам")
    return Table(title, columns, rows, totals, notes)


REPORTS = {"funnel": funnel, "storage": storage, "acceptance": acceptance}

__all__ = ["REPORTS"]
