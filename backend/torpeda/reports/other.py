"""Прочие отчёты (этап 5): коэффициенты приёмки, география заказов, совместные покупки,
покатушки без продаж, история цен."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import combinations

from sqlalchemy import select
from sqlalchemy.orm import Session

from torpeda.db import DEFAULT_ACCOUNT_ID
from torpeda.db.models import AcceptanceCoef, Order, PriceChange, Product, ReportRow

from . import Column, Table

ACC = DEFAULT_ACCOUNT_ID
ZERO = Decimal(0)
NM_COLUMNS = [Column("nm_id", "Артикул WB", "text"), Column("sa_name", "Артикул продавца", "text")]


def _products(s: Session) -> dict[int, Product]:
    return {p.nm_id: p for p in s.scalars(select(Product).where(Product.account_id == ACC))}


def _pct(a, b) -> Decimal | None:
    return (Decimal(a) * 100 / Decimal(b)).quantize(Decimal("0.1")) if b else None


def _orders(s: Session, date_from: date, date_to: date) -> list[Order]:
    q = select(Order).where(
        Order.account_id == ACC,
        Order.is_cancel.is_(False),
        Order.date >= datetime.combine(date_from, datetime.min.time()),
        Order.date < datetime.combine(date_to + timedelta(days=1), datetime.min.time()),
    )
    return list(s.scalars(q))


# --- коэффициенты приёмки ---

BOX_TYPES = {"box": (2, "короба"), "pallet": (5, "монопаллеты"), "safe": (6, "суперсейф")}


def coefficients(s: Session, date_from: date, date_to: date, group: str = "box") -> Table:
    group = group if group in BOX_TYPES else "box"
    box_id, box_name = BOX_TYPES[group]
    rows_db = list(
        s.scalars(select(AcceptanceCoef).where(AcceptanceCoef.account_id == ACC, AcceptanceCoef.box_type_id == box_id))
    )
    days = sorted({c.date for c in rows_db})
    data: dict[str, dict] = defaultdict(dict)
    for c in rows_db:
        ok = c.allow_unload and c.coefficient is not None and c.coefficient >= 0
        data[c.warehouse or str(c.warehouse_id)][f"d_{c.date.isoformat()}"] = c.coefficient if ok else None
        data[c.warehouse or str(c.warehouse_id)].setdefault("storage_coef", c.storage_coef)
        data[c.warehouse or str(c.warehouse_id)].setdefault("delivery_coef", c.delivery_coef)
    rows = []
    for wh, r in data.items():
        values = [r.get(f"d_{d.isoformat()}") for d in days]
        r |= {
            "warehouse": wh,
            "free_days": sum(1 for v in values if v == 0),
            "open_days": sum(1 for v in values if v is not None),
        }
        rows.append(r)
    rows.sort(key=lambda r: (-r["free_days"], -r["open_days"], r["warehouse"]))
    columns = [
        Column("warehouse", "Склад", "text"),
        Column("free_days", "Бесплатных дней", "int"),
        Column("open_days", "Дней с приёмкой", "int"),
        Column("delivery_coef", "Логистика, %", "num"),
        Column("storage_coef", "Хранение, %", "num"),
    ] + [Column(f"d_{d.isoformat()}", d.strftime("%d.%m"), "num") for d in days]
    notes = [
        f"Приёмка: {box_name}. 0 — бесплатно, 1 — обычный тариф, 2 — тариф ×2, пусто — приёмки нет.",
        "Это прогноз WB на ближайшие дни, даты отчёта на него не влияют.",
        "Обновляется кнопкой «Загрузить коэффициенты из WB».",
    ]
    if rows_db:
        notes.insert(0, f"Загружено {max(c.loaded_at for c in rows_db):%d.%m.%Y %H:%M}.")
    return Table(f"Коэффициенты приёмки: {box_name}", columns, rows, None, notes)


# --- география заказов ---


def geography(s: Session, date_from: date, date_to: date, group: str = "okrug") -> Table:
    group = group if group in ("okrug", "region", "warehouse") else "okrug"
    orders = _orders(s, date_from, date_to)
    total = len(orders)
    if group == "warehouse":
        by_wh: dict[str, Counter] = defaultdict(Counter)
        for o in orders:
            by_wh[o.warehouse or "—"][o.oblast or "—"] += 1
        rows = []
        for wh, cnt in by_wh.items():
            n = sum(cnt.values())
            for okrug, k in cnt.most_common():
                rows.append({"warehouse": wh, "okrug": okrug, "orders": k, "share": _pct(k, n), "wh_orders": n})
        rows.sort(key=lambda r: (-r["wh_orders"], -r["orders"]))
        columns = [
            Column("warehouse", "Склад отгрузки", "text"),
            Column("okrug", "Округ покупателя", "text"),
            Column("orders", "Заказы, шт", "int"),
            Column("share", "Доля заказов склада, %", "pct"),
        ]
        title = "Откуда и куда везут заказы"
    else:
        key = (lambda o: o.oblast or "—") if group == "okrug" else (lambda o: o.region or "—")
        cnt = Counter(key(o) for o in orders)
        sums: dict[str, Decimal] = defaultdict(lambda: ZERO)
        nms: dict[str, set] = defaultdict(set)
        for o in orders:
            sums[key(o)] += o.price_with_disc or ZERO
            nms[key(o)].add(o.nm_id)
        rows = [
            {"place": p, "orders": k, "share": _pct(k, total), "orders_sum": sums[p], "nm_count": len(nms[p])}
            for p, k in cnt.most_common()
        ]
        columns = [
            Column("place", "Округ" if group == "okrug" else "Регион", "text"),
            Column("orders", "Заказы, шт", "int"),
            Column("share", "Доля, %", "pct"),
            Column("orders_sum", "Заказы, руб"),
            Column("nm_count", "Артикулов", "int"),
        ]
        title = "Заказы по округам" if group == "okrug" else "Заказы по регионам"
    totals = {columns[0].field: "Итого", "orders": total}
    notes = [
        "По заказам без отмен. Локализацию (доля заказов со склада в регионе покупателя) WB показывает в воронке."
    ]
    return Table(title, columns, rows, totals, notes)


# --- совместные покупки ---


def joint_sales(s: Session, date_from: date, date_to: date) -> Table:
    baskets: dict[str, set[int]] = defaultdict(set)
    per_nm: Counter = Counter()
    for o in _orders(s, date_from, date_to):
        if o.g_number:
            baskets[o.g_number].add(o.nm_id)
    for nms in baskets.values():
        for nm in nms:
            per_nm[nm] += 1
    pairs: Counter = Counter()
    for nms in baskets.values():
        for a, b in combinations(sorted(nms), 2):
            pairs[(a, b)] += 1
    products = _products(s)

    def sa(nm: int) -> str | None:
        p = products.get(nm)
        return p.vendor_code if p else None

    rows = []
    for (a, b), k in pairs.most_common():
        rows.append(
            {
                "nm_a": a,
                "sa_a": sa(a),
                "nm_b": b,
                "sa_b": sa(b),
                "baskets": k,
                "share_a": _pct(k, per_nm[a]),
                "share_b": _pct(k, per_nm[b]),
            }
        )
    columns = [
        Column("nm_a", "Товар 1", "text"),
        Column("sa_a", "Артикул продавца 1", "text"),
        Column("nm_b", "Товар 2", "text"),
        Column("sa_b", "Артикул продавца 2", "text"),
        Column("baskets", "Купили вместе, раз", "int"),
        Column("share_a", "Доля заказов товара 1, %", "pct"),
        Column("share_b", "Доля заказов товара 2, %", "pct"),
    ]
    multi = sum(1 for nms in baskets.values() if len(nms) > 1)
    notes = [f"Корзин с двумя и больше вашими товарами: {multi} из {len(baskets)}. По заказам без отмен."]
    return Table("Совместные покупки", columns, rows, None, notes)


# --- покатушки без продаж ---


def rides(s: Session, date_from: date, date_to: date) -> Table:
    q = select(ReportRow).where(
        ReportRow.account_id == ACC, ReportRow.rr_dt >= date_from, ReportRow.rr_dt <= date_to
    )
    data: dict[int, dict] = defaultdict(lambda: {"deliveries": 0, "back": 0, "logistics": ZERO, "net": 0})
    for r in s.scalars(q):
        if not r.nm_id:
            continue
        a = data[r.nm_id]
        a["deliveries"] += r.delivery_amount or 0
        a["back"] += r.return_amount or 0
        a["logistics"] += r.delivery_rub or ZERO
        oper = (r.supplier_oper_name or "").strip().lower()
        if oper in ("продажа", "возврат"):
            a["net"] += (-1 if oper == "возврат" else 1) * (r.quantity or 0)
    products = _products(s)
    rows = []
    total = {"deliveries": 0, "back": 0, "logistics": ZERO, "wasted_trips": 0, "wasted_rub": ZERO, "net": 0}
    for nm, a in data.items():
        trips = a["deliveries"] + a["back"]
        if not trips:
            continue
        per_trip = a["logistics"] / trips
        useful = min(max(a["net"], 0), a["deliveries"])
        wasted_trips = trips - useful
        wasted = (per_trip * wasted_trips).quantize(Decimal("0.01"))
        p = products.get(nm)
        rows.append(
            {
                "nm_id": nm,
                "sa_name": p.vendor_code if p else None,
                "deliveries": a["deliveries"],
                "back": a["back"],
                "net": a["net"],
                "buyout_pct": _pct(max(a["net"], 0), a["deliveries"]),
                "logistics": a["logistics"],
                "per_trip": per_trip.quantize(Decimal("0.01")),
                "wasted_trips": wasted_trips,
                "wasted_rub": wasted,
                "wasted_per_sale": (wasted / a["net"]).quantize(Decimal("0.01")) if a["net"] > 0 else None,
            }
        )
        for k in ("deliveries", "back", "logistics", "net"):
            total[k] += a[k]
        total["wasted_trips"] += wasted_trips
        total["wasted_rub"] += wasted
    rows.sort(key=lambda r: r["wasted_rub"], reverse=True)
    columns = NM_COLUMNS + [
        Column("deliveries", "Поездок к покупателю", "int"),
        Column("back", "Поездок обратно", "int"),
        Column("net", "Продано − возвраты, шт", "int"),
        Column("buyout_pct", "Выкуп, %", "pct"),
        Column("logistics", "Логистика, руб"),
        Column("per_trip", "За поездку, руб"),
        Column("wasted_trips", "Поездок без продажи", "int"),
        Column("wasted_rub", "Логистика без продажи, руб"),
        Column("wasted_per_sale", "Лишняя логистика на 1 продажу, руб"),
    ]
    totals = total | {"nm_id": "Итого", "buyout_pct": _pct(max(total["net"], 0), total["deliveries"])}
    notes = [
        "По финотчётам. Поездка без продажи — товар съездил к покупателю и не был выкуплен, плюс обратная дорога.",
        "Логистика без продажи — оценка: средняя цена поездки × число таких поездок.",
    ]
    return Table("Покатушки без продаж", columns, rows, totals, notes)


# --- история цен ---


def price_history(s: Session, date_from: date, date_to: date) -> Table:
    q = (
        select(PriceChange)
        .where(
            PriceChange.account_id == ACC,
            PriceChange.sent_at >= datetime.combine(date_from, datetime.min.time()),
            PriceChange.sent_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time()),
        )
        .order_by(PriceChange.sent_at.desc())
    )
    products = _products(s)
    rows = []
    for c in s.scalars(q):
        old = c.old_price * (100 - c.old_discount_pct) / 100
        new = c.new_price * (100 - c.new_discount_pct) / 100
        p = products.get(c.nm_id)
        rows.append(
            {
                "at": c.sent_at.strftime("%d.%m.%Y %H:%M"),
                "nm_id": c.nm_id,
                "sa_name": p.vendor_code if p else None,
                "old_price": c.old_price,
                "old_discount": c.old_discount_pct,
                "old_final": old.quantize(Decimal("0.01")),
                "new_price": c.new_price,
                "new_discount": c.new_discount_pct,
                "new_final": new.quantize(Decimal("0.01")),
                "change_pct": _pct(new - old, old),
                "status": "отправлено" if c.status == "sent" else f"ошибка: {c.error or ''}",
            }
        )
    columns = [Column("at", "Когда", "text")] + NM_COLUMNS + [
        Column("old_price", "Было: цена до скидки"),
        Column("old_discount", "Было: скидка, %", "pct"),
        Column("old_final", "Было: цена со скидкой"),
        Column("new_price", "Стало: цена до скидки"),
        Column("new_discount", "Стало: скидка, %", "pct"),
        Column("new_final", "Стало: цена со скидкой"),
        Column("change_pct", "Изменение, %", "pct"),
        Column("status", "Результат", "text"),
    ]
    notes = ["Цены, отправленные из Торпеды. Вернуть прежнюю цену можно на вкладке «Журнал цен»."]
    return Table("История цен", columns, rows, None, notes)


REPORTS = {
    "coefficients": coefficients,
    "geography": geography,
    "joint_sales": joint_sales,
    "rides": rides,
    "price_history": price_history,
}

__all__ = ["REPORTS"]
