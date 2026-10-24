"""Остатки в штуках и деньгах (этап 3).

Остатки — снимок на момент последней загрузки из WB, даты отчёта на него не влияют.
Даты задают период, по которому считается скорость заказов и на сколько дней хватит остатка.
Деньги: по себестоимости (на сегодня) и по текущей цене продавца после его скидки.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from torpeda.db import DEFAULT_ACCOUNT_ID
from torpeda.db.models import Order, Price, Product, Stock
from torpeda.services import current_costs

from . import Column, Table

ACC = DEFAULT_ACCOUNT_ID
ZERO = Decimal(0)


def _seller_prices(s: Session) -> dict[int, Decimal]:
    out = {}
    for p in s.scalars(select(Price).where(Price.account_id == ACC)):
        out[p.nm_id] = (p.price * (100 - (p.discount_pct or ZERO)) / 100).quantize(Decimal("0.01"))
    return out


def _orders_per_nm(s: Session, date_from: date, date_to: date) -> dict[int, int]:
    q = (
        select(Order.nm_id, func.count())
        .where(
            Order.account_id == ACC,
            Order.is_cancel.is_(False),
            Order.date >= datetime.combine(date_from, datetime.min.time()),
            Order.date < datetime.combine(date_to + timedelta(days=1), datetime.min.time()),
        )
        .group_by(Order.nm_id)
    )
    return dict(s.execute(q).all())


@dataclass
class Agg:
    fbo: int = 0
    fbs: int = 0
    to_client: int = 0
    from_client: int = 0
    cost_sum: Decimal = ZERO
    price_sum: Decimal = ZERO
    no_cost: int = 0
    nms: set = field(default_factory=set)

    def add(self, st: Stock, cost: Decimal | None, price: Decimal | None) -> None:
        if st.scheme == "FBS":
            self.fbs += st.quantity
        else:
            self.fbo += st.quantity
        self.to_client += st.in_way_to_client or 0
        self.from_client += st.in_way_from_client or 0
        if cost is None:
            self.no_cost += st.quantity
        else:
            self.cost_sum += cost * st.quantity
        if price is not None:
            self.price_sum += price * st.quantity
        self.nms.add(st.nm_id)

    def row(self) -> dict:
        return {
            "fbo": self.fbo,
            "fbs": self.fbs,
            "total": self.fbo + self.fbs,
            "to_client": self.to_client,
            "from_client": self.from_client,
            "cost_sum": self.cost_sum,
            "price_sum": self.price_sum,
        }


MONEY_COLUMNS = [
    Column("fbo", "FBO (склады WB), шт", "int"),
    Column("fbs", "FBS (свои склады), шт", "int"),
    Column("total", "Всего, шт", "int"),
    Column("to_client", "В пути к покупателю, шт", "int"),
    Column("from_client", "Возвращается, шт", "int"),
    Column("cost_sum", "По себестоимости, руб"),
    Column("price_sum", "По цене продавца, руб"),
]


def _snapshot(s: Session) -> tuple[list[Stock], list[str]]:
    rows = list(s.scalars(select(Stock).where(Stock.account_id == ACC)))
    notes = []
    if rows:
        at = max(r.snapshot_at for r in rows)
        notes.append(f"Остатки на {at:%d.%m.%Y %H:%M} (последняя загрузка из WB), даты отчёта на них не влияют.")
    else:
        notes.append("Остатков нет. Нажмите «Загрузить из WB» вверху справа.")
    return rows, notes


def stocks(s: Session, date_from: date, date_to: date, group: str = "nm") -> Table:
    group = group if group in ("nm", "warehouse", "nm_warehouse") else "nm"
    rows_st, notes = _snapshot(s)
    costs = current_costs(s, date.today())
    prices = _seller_prices(s)
    products = {p.nm_id: p for p in s.scalars(select(Product).where(Product.account_id == ACC))}

    def keyf(st: Stock) -> tuple:
        if group == "nm":
            return (st.nm_id,)
        if group == "warehouse":
            return (st.scheme, st.warehouse)
        return (st.nm_id, st.scheme, st.warehouse)

    data: dict[tuple, Agg] = defaultdict(Agg)
    total = Agg()
    for st in rows_st:
        cost, price = costs.get(st.nm_id), prices.get(st.nm_id)
        data[keyf(st)].add(st, cost, price)
        total.add(st, cost, price)

    days = (date_to - date_from).days + 1
    orders = _orders_per_nm(s, date_from, date_to) if group == "nm" else {}
    rows = []
    for key, a in data.items():
        r = a.row()
        if group != "warehouse":
            p = products.get(key[0])
            r |= {
                "nm_id": key[0],
                "sa_name": p.vendor_code if p else None,
                "subject": p.subject_name if p else None,
                "cost": costs.get(key[0]),
                "price": prices.get(key[0]),
            }
        if group != "nm":
            r |= {"scheme": key[-2], "warehouse": key[-1]}
        if group == "warehouse":
            r["nm_count"] = len(a.nms)
        if group == "nm":
            per_day = Decimal(orders.get(key[0], 0)) / days
            r["orders_per_day"] = per_day.quantize(Decimal("0.1"))
            r["days_left"] = int(r["total"] / per_day) if per_day else None
        rows.append(r)
    rows.sort(key=lambda r: r["cost_sum"], reverse=True)

    head: list[Column] = []
    if group != "warehouse":
        head += [
            Column("nm_id", "Артикул WB", "text"),
            Column("sa_name", "Артикул продавца", "text"),
            Column("subject", "Предмет", "text"),
        ]
    if group != "nm":
        head += [Column("scheme", "Схема", "text"), Column("warehouse", "Склад", "text")]
    if group == "warehouse":
        head.append(Column("nm_count", "Артикулов", "int"))
    columns = head + MONEY_COLUMNS
    if group != "warehouse":
        columns[len(head) : len(head)] = [
            Column("cost", "Себестоимость, руб"),
            Column("price", "Цена продавца, руб"),
        ]
    if group == "nm":
        columns += [
            Column("orders_per_day", "Заказов в день", "num"),
            Column("days_left", "Хватит на дней", "int"),
        ]
        notes.append(f"Заказов в день — среднее за выбранные даты ({days} дн.), без отмен.")
    if total.no_cost:
        notes.append(f"Без себестоимости {total.no_cost} шт: они не вошли в сумму по себестоимости.")

    totals = total.row()
    first = columns[0].field
    totals[first] = "Итого"
    if group == "warehouse":
        totals["nm_count"] = len(total.nms)
    titles = {"nm": "по артикулам", "warehouse": "по складам", "nm_warehouse": "по артикулам и складам"}
    return Table(f"Остатки {titles[group]}", columns, rows, totals, notes)


REPORTS = {"stocks": stocks}

__all__ = ["REPORTS"]
