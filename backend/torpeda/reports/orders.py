"""Заказы и продажи по API статистики (этап 2).

WB хранит заказы 90 дней, поэтому отчёты по заказам — за последние 3 месяца.
Заказ и продажа связаны полем srid: так считаются выкуп по заказам и время доставки.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from torpeda.db import DEFAULT_ACCOUNT_ID
from torpeda.db.models import Order, Plan, Product, Sale

from . import Column, Table

ACC = DEFAULT_ACCOUNT_ID
ZERO = Decimal(0)


def _orders(s: Session, date_from: date, date_to: date) -> list[Order]:
    q = select(Order).where(
        Order.account_id == ACC, Order.date >= _start(date_from), Order.date < _start(date_to + timedelta(days=1))
    )
    return list(s.scalars(q))


def _sales(s: Session, date_from: date, date_to: date) -> list[Sale]:
    q = select(Sale).where(
        Sale.account_id == ACC, Sale.date >= _start(date_from), Sale.date < _start(date_to + timedelta(days=1))
    )
    return list(s.scalars(q))


def _start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day)


def _is_return(sale: Sale) -> bool:
    return sale.sale_id.startswith("R")


def _pct(a: float | Decimal, b: float | Decimal) -> Decimal | None:
    return Decimal(a) / Decimal(b) * 100 if b else None


def _avg(values: list) -> Decimal | None:
    values = [v for v in values if v is not None]
    return sum(values, ZERO) / len(values) if values else None


def _titles(s: Session) -> dict[int, tuple[str | None, str | None]]:
    return {
        p.nm_id: (p.vendor_code, p.subject_name) for p in s.scalars(select(Product).where(Product.account_id == ACC))
    }


GROUPS = {
    "nm": ("по артикулам", lambda x: (x.nm_id,), [Column("nm_id", "Артикул WB", "text")]),
    "nm_size": (
        "по артикулам и размерам",
        lambda x: (x.nm_id, x.tech_size or ""),
        [Column("nm_id", "Артикул WB", "text"), Column("tech_size", "Размер", "text")],
    ),
    "day": ("по дням", lambda x: (x.date.date(),), [Column("day", "Дата", "date")]),
    "warehouse": ("по складам", lambda x: (x.warehouse or "—",), [Column("warehouse", "Склад", "text")]),
    "region": ("по регионам", lambda x: (x.region or "—",), [Column("region", "Регион", "text")]),
}


def _key_row(group: str, key: tuple, titles: dict) -> dict:
    cols = GROUPS[group][2]
    row = {c.field: v for c, v in zip(cols, key, strict=True)}
    if "nm_id" in row:
        row["sa_name"], row["subject"] = titles.get(row["nm_id"], (None))
    return row


def _key_columns(group: str) -> list[Column]:
    cols = list(GROUPS[group][2])
    if cols[0].field == "nm_id":
        cols[1:1] = [Column("sa_name", "Артикул продавца", "text"), Column("subject", "Предмет", "text")]
    return cols


# --- 1. Заказы и продажи за период ---


@dataclass
class OS:
    orders: int = 0
    orders_sum: Decimal = ZERO
    cancels: int = 0
    sales: int = 0
    sales_sum: Decimal = ZERO
    returns: int = 0
    returns_sum: Decimal = ZERO
    for_pay: Decimal = ZERO

    def __post_init__(self):
        self.spp: list = []
        self.finished: list = []

    def row(self) -> dict:
        net = self.sales - self.returns
        return {
            "orders": self.orders,
            "orders_sum": self.orders_sum,
            "cancels": self.cancels,
            "sales": self.sales,
            "returns": self.returns,
            "net": net,
            "net_sum": self.sales_sum - self.returns_sum,
            "for_pay": self.for_pay,
            "buyout_pct": _pct(net, self.orders - self.cancels),
            "spp": _avg(self.spp),
            "avg_finished": _avg(self.finished),
        }


def orders_sales(s: Session, date_from: date, date_to: date, group: str = "nm") -> Table:
    group = group if group in GROUPS else "nm"
    keyf = GROUPS[group][1]
    data: dict[tuple, OS] = defaultdict(OS)
    total = OS()
    for o in _orders(s, date_from, date_to):
        for a in (data[keyf(o)], total):
            a.orders += 1
            a.orders_sum += o.price_with_disc or ZERO
            a.cancels += 1 if o.is_cancel else 0
            a.spp.append(o.spp)
            a.finished.append(o.finished_price)
    for x in _sales(s, date_from, date_to):
        for a in (data[keyf(x)], total):
            if _is_return(x):
                a.returns += 1
                a.returns_sum += abs(x.price_with_disc or ZERO)
                a.for_pay -= abs(x.for_pay or ZERO)
            else:
                a.sales += 1
                a.sales_sum += x.price_with_disc or ZERO
                a.for_pay += x.for_pay or ZERO
    titles = _titles(s)
    rows = [_key_row(group, k, titles) | a.row() for k, a in data.items()]
    rows.sort(key=lambda r: r.get("day") or r["orders_sum"], reverse=True)
    columns = _key_columns(group) + [
        Column("orders", "Заказы, шт", "int"),
        Column("orders_sum", "Заказы, руб"),
        Column("cancels", "Отмены, шт", "int"),
        Column("sales", "Продажи, шт", "int"),
        Column("returns", "Возвраты, шт", "int"),
        Column("net", "Продажи − возвраты, шт", "int"),
        Column("net_sum", "Продажи − возвраты, руб"),
        Column("for_pay", "К перечислению, руб"),
        Column("buyout_pct", "Выкуп, %", "pct"),
        Column("spp", "Средняя СПП, %", "pct"),
        Column("avg_finished", "Средняя цена покупателя, руб"),
    ]
    totals = {columns[0].field: "Итого"} | total.row()
    notes = [
        "Суммы — в цене продавца (после его скидки, до СПП). Выкуп здесь — продажи за период к заказам за период, "
        "точный выкуп по каждому заказу — в отчёте «Процент выкупа»."
    ]
    return Table(f"Заказы и продажи {GROUPS[group][0]}", columns, rows, totals, notes)


# --- 2. Процент выкупа по заказам (srid) ---


def buyout(s: Session, date_from: date, date_to: date, group: str = "nm") -> Table:
    group = group if group in ("nm", "nm_size", "warehouse", "region") else "nm"
    keyf = GROUPS[group][1]
    sold_srids, returned_srids = set(), set()
    for x in _sales(s, date_from, date_to + timedelta(days=60)):  # выкуп случается позже заказа
        (returned_srids if _is_return(x) else sold_srids).add(x.srid)
    data: dict[tuple, dict] = defaultdict(lambda: defaultdict(int))
    total: dict = defaultdict(int)
    for o in _orders(s, date_from, date_to):
        if o.is_cancel:
            st = "cancelled"
        elif o.srid in returned_srids:
            st = "returned"
        elif o.srid in sold_srids:
            st = "sold"
        else:
            st = "in_transit"
        for a in (data[keyf(o)], total):
            a["orders"] += 1
            a[st] += 1

    def row(a: dict) -> dict:
        finished = a["sold"] + a["returned"] + a["cancelled"]
        return {
            "orders": a["orders"],
            "sold": a["sold"],
            "returned": a["returned"],
            "cancelled": a["cancelled"],
            "in_transit": a["in_transit"],
            "buyout_pct": _pct(a["sold"], finished),
            "return_pct": _pct(a["returned"], a["sold"] + a["returned"]),
        }

    titles = _titles(s)
    rows = [_key_row(group, k, titles) | row(a) for k, a in data.items()]
    rows.sort(key=lambda r: r["orders"], reverse=True)
    columns = _key_columns(group) + [
        Column("orders", "Заказы, шт", "int"),
        Column("sold", "Выкуплено, шт", "int"),
        Column("returned", "Возврат, шт", "int"),
        Column("cancelled", "Отказ / отмена, шт", "int"),
        Column("in_transit", "Ещё в пути, шт", "int"),
        Column("buyout_pct", "Выкуп, %", "pct"),
        Column("return_pct", "Возвраты от выкупа, %", "pct"),
    ]
    totals = {columns[0].field: "Итого"} | row(total)
    notes = [
        "Каждый заказ периода отслежен по srid: выкуплен, возвращён, отменён или ещё в пути. "
        "Выкуп = выкуплено / (выкуплено + возврат + отказ). Заказы последних дней ещё в пути, поэтому берите период "
        "не позже чем 2 недели назад."
    ]
    return Table(f"Процент выкупа {GROUPS[group][0]}", columns, rows, totals, notes)


# --- 3. Время доставки ---


def delivery_time(s: Session, date_from: date, date_to: date, group: str = "nm") -> Table:
    group = group if group in ("nm", "warehouse", "region") else "nm"
    orders = {o.srid: o for o in s.scalars(select(Order).where(Order.account_id == ACC))}
    days: dict[tuple, list[float]] = defaultdict(list)
    all_days: list[float] = []
    for x in _sales(s, date_from, date_to):
        o = orders.get(x.srid)
        if _is_return(x) or o is None or x.date < o.date:
            continue
        d = (x.date - o.date).total_seconds() / 86400
        days[GROUPS[group][1](o)].append(d)
        all_days.append(d)

    def row(v: list[float]) -> dict:
        return {
            "count": len(v),
            "avg_days": Decimal(str(round(statistics.mean(v), 1))),
            "median_days": Decimal(str(round(statistics.median(v), 1))),
            "max_days": Decimal(str(round(max(v), 1))),
        }

    titles = _titles(s)
    rows = [_key_row(group, k, titles) | row(v) for k, v in days.items()]
    rows.sort(key=lambda r: r["avg_days"], reverse=True)
    columns = _key_columns(group) + [
        Column("count", "Выкупов, шт", "int"),
        Column("avg_days", "Среднее, дней", "num"),
        Column("median_days", "Медиана, дней", "num"),
        Column("max_days", "Максимум, дней", "num"),
    ]
    totals = ({columns[0].field: "Итого"} | row(all_days)) if all_days else None
    notes = ["От оформления заказа до выкупа покупателем. Склад — склад отгрузки, регион — регион покупателя."]
    title = f"Время доставки {GROUPS[group][0]}"
    return Table(title, columns, rows, totals, notes)


# --- 4. Динамика СПП ---


def spp(s: Session, date_from: date, date_to: date, group: str = "day") -> Table:
    group = group if group in ("day", "nm") else "day"
    keyf = GROUPS[group][1]
    data: dict[tuple, list[Order]] = defaultdict(list)
    for o in _orders(s, date_from, date_to):
        data[keyf(o)].append(o)

    def row(v: list[Order]) -> dict:
        return {
            "orders": len(v),
            "spp": _avg([o.spp for o in v]),
            "spp_min": min((o.spp for o in v if o.spp is not None), default=None),
            "spp_max": max((o.spp for o in v if o.spp is not None), default=None),
            "price": _avg([o.price_with_disc for o in v]),
            "finished": _avg([o.finished_price for o in v]),
        }

    titles = _titles(s)
    rows = [_key_row(group, k, titles) | row(v) for k, v in data.items()]
    rows.sort(key=lambda r: r.get("day") or r["orders"], reverse=True)
    columns = _key_columns(group) + [
        Column("orders", "Заказы, шт", "int"),
        Column("spp", "СПП средняя, %", "pct"),
        Column("spp_min", "СПП мин, %", "pct"),
        Column("spp_max", "СПП макс, %", "pct"),
        Column("price", "Цена продавца, руб"),
        Column("finished", "Цена покупателя, руб"),
    ]
    all_orders = [o for v in data.values() for o in v]
    totals = ({columns[0].field: "Итого"} | row(all_orders)) if all_orders else None
    return Table(f"Динамика СПП {GROUPS[group][0]}", columns, rows, totals, ["СПП — скидка WB, по заказам."])


# --- 5. ABC-анализ ---


def _abc(values: dict) -> dict:
    """A — товары, дающие первые 80% суммы, B — следующие 15%, C — остальные."""
    total = sum((v for v in values.values() if v > 0), 0)
    out, acc = {}, 0
    for k, v in sorted(values.items(), key=lambda kv: kv[1], reverse=True):
        if v <= 0 or not total:
            out[k] = "C"
            continue
        acc += v
        share = acc / total
        out[k] = "A" if share <= 0.8 or acc == v else "B" if share <= 0.95 else "C"
    return out


def abc(s: Session, date_from: date, date_to: date) -> Table:
    from torpeda.reports import finance

    orders_qty: dict[int, int] = defaultdict(int)
    revenue: dict[int, Decimal] = defaultdict(lambda: ZERO)
    monthly: dict[str, dict[int, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    for o in _orders(s, date_from, date_to):
        if not o.is_cancel:
            orders_qty[o.nm_id] += 1
    for x in _sales(s, date_from, date_to):
        amount = abs(x.price_with_disc or ZERO) * (-1 if _is_return(x) else 1)
        revenue[x.nm_id] += amount
        monthly[x.date.strftime("%Y-%m")][x.nm_id] += amount
    detail = finance.detail(s, date_from, date_to, "nm")
    profit = {r["nm_id"]: r["profit"] for r in detail.rows if r["nm_id"] != finance.NO_NM}

    nms = set(orders_qty) | set(revenue) | set(profit)
    abc_orders = _abc({n: orders_qty.get(n, 0) for n in nms})
    abc_revenue = _abc({n: revenue.get(n, ZERO) for n in nms})
    abc_profit = _abc({n: profit[n] for n in profit}) if profit else {}
    months = sorted(monthly)
    abc_month = {m: _abc(dict(monthly[m])) for m in months}
    titles = _titles(s)
    rows = []
    for n in nms:
        row = {
            "nm_id": n,
            "sa_name": titles.get(n, (None))[0],
            "subject": titles.get(n, (None))[1],
            "abc": abc_orders[n] + abc_revenue[n] + (abc_profit.get(n, "–") if profit else ""),
            "orders": orders_qty.get(n, 0),
            "revenue": revenue.get(n, ZERO),
            "profit": profit.get(n),
            "abc_orders": abc_orders[n],
            "abc_revenue": abc_revenue[n],
            "abc_profit": abc_profit.get(n),
        }
        for m in months:
            row[f"m_{m}"] = abc_month[m].get(n, "–")
        rows.append(row)
    rows.sort(key=lambda r: r["revenue"], reverse=True)
    columns = [
        Column("nm_id", "Артикул WB", "text"),
        Column("sa_name", "Артикул продавца", "text"),
        Column("subject", "Предмет", "text"),
        Column("abc", "Группа (заказы, выручка, прибыль)", "text"),
        Column("orders", "Заказы, шт", "int"),
        Column("revenue", "Выручка, руб"),
        Column("profit", "Прибыль по финотчётам, руб"),
        Column("abc_orders", "ABC заказы", "text"),
        Column("abc_revenue", "ABC выручка", "text"),
        Column("abc_profit", "ABC прибыль", "text"),
    ] + [Column(f"m_{m}", f"Выручка {m}", "text") for m in months]
    totals = {
        "nm_id": "Итого",
        "orders": sum(orders_qty.values()),
        "revenue": sum(revenue.values(), ZERO),
        "profit": sum(profit.values(), ZERO) if profit else None,
    }
    notes = [
        "A — товары, которые дают первые 80% суммы, B — следующие 15%, C — остальные. "
        "Колонки по месяцам — группа по выручке в этом месяце. Прибыль — из финотчётов за те же даты."
    ]
    return Table("ABC-анализ", columns, rows, totals, notes)


# --- 6. План-факт ---


def _months(date_from: date, date_to: date) -> list[str]:
    out, d = [], date(date_from.year, date_from.month, 1)
    while d <= date_to:
        out.append(d.strftime("%Y-%m"))
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def plan_fact(s: Session, date_from: date, date_to: date) -> Table:
    months = _months(date_from, date_to)
    first = date.fromisoformat(months[0] + "-01")
    last_m = date.fromisoformat(months[-1] + "-01")
    last = date(last_m.year + (last_m.month == 12), last_m.month % 12 + 1, 1) - timedelta(days=1)
    fact: dict[tuple[str, int], dict] = defaultdict(lambda: {"orders": 0, "net": 0, "revenue": ZERO})
    for o in _orders(s, first, last):
        if not o.is_cancel:
            for nm in (o.nm_id, 0):
                fact[(o.date.strftime("%Y-%m"), nm)]["orders"] += 1
    for x in _sales(s, first, last):
        sign = -1 if _is_return(x) else 1
        for nm in (x.nm_id, 0):
            f = fact[(x.date.strftime("%Y-%m"), nm)]
            f["net"] += sign
            f["revenue"] += sign * abs(x.price_with_disc or ZERO)
    plans = {
        (p.month, p.nm_id): p for p in s.scalars(select(Plan).where(Plan.account_id == ACC, Plan.month.in_(months)))
    }
    titles = _titles(s)
    nms = sorted(set(titles) | {nm for (_, nm) in fact if nm} | {nm for (_, nm) in plans if nm})
    rows = []
    for m in months:
        for nm in [0, *nms]:
            f = fact.get((m, nm), {"orders": 0, "net": 0, "revenue": ZERO})
            p = plans.get((m, nm))
            if nm and not p and not f["orders"] and not f["net"]:
                continue
            rows.append(
                {
                    "month": m,
                    "nm_id": nm or "Весь кабинет",
                    "sa_name": titles.get(nm, (None))[0] if nm else None,
                    "plan_qty": p.qty if p else None,
                    "fact_qty": f["net"],
                    "qty_pct": _pct(f["net"], p.qty) if p and p.qty else None,
                    "plan_revenue": p.revenue if p else None,
                    "fact_revenue": f["revenue"],
                    "revenue_pct": _pct(f["revenue"], p.revenue) if p and p.revenue else None,
                    "orders": f["orders"],
                }
            )
    columns = [
        Column("month", "Месяц", "text"),
        Column("nm_id", "Артикул WB", "text"),
        Column("sa_name", "Артикул продавца", "text"),
        Column("plan_qty", "План, шт", "int", editable=True),
        Column("fact_qty", "Факт продаж − возвратов, шт", "int"),
        Column("qty_pct", "Выполнение по шт, %", "pct"),
        Column("plan_revenue", "План, руб", editable=True),
        Column("fact_revenue", "Факт выручки, руб"),
        Column("revenue_pct", "Выполнение по выручке, %", "pct"),
        Column("orders", "Заказы, шт", "int"),
    ]
    notes = [
        "План вводите прямо в таблице: двойной щелчок по ячейке «План», Enter — сохранить. Выручка — в цене продавца."
    ]
    return Table("План-факт", columns, rows, None, notes)


def save_plan(s: Session, month: str, nm_id: int, qty: int | None, revenue: Decimal | None) -> None:
    p = s.get(Plan, (ACC, month, nm_id)) or Plan(account_id=ACC, month=month, nm_id=nm_id)
    p.qty, p.revenue = qty, revenue
    s.merge(p)
    s.commit()


REPORTS = {
    "orders_sales": orders_sales,
    "buyout": buyout,
    "delivery_time": delivery_time,
    "spp": spp,
    "abc": abc,
    "plan_fact": plan_fact,
}
