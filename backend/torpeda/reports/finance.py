"""Финансовые отчёты по детализации недельных отчётов WB (этап 1).

Маржа считается по формуле, сверенной с «Ракетой» (torpeda.calc.report, docs/formulas.md):
к перечислению за продажи − возвраты + компенсация по программе лояльности − баллы − участие в программе
(поля cashback_* строк детализации)
− логистика − хранение − платная приёмка − штрафы − прочие удержания + доплаты − налог − себестоимость.
Реклама добавится на этапе 4.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass, fields
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from torpeda.calc.report import ReportTotals, calculate_report
from torpeda.db import DEFAULT_ACCOUNT_ID
from torpeda.db.models import CostPrice, ReportRow, SalesReport
from torpeda.services import get_settings

from . import Column, Table
from .ads import ad_spend_by_nm

__all__ = ["REPORTS", "NO_NM"]

ACC = DEFAULT_ACCOUNT_ID
ZERO = Decimal(0)
NO_NM = "без артикула"


# --- разбор строки детализации ---


def _oper(r: ReportRow) -> str:
    return (r.supplier_oper_name or "").strip().lower()


def _is_return(r: ReportRow) -> bool:
    return (r.doc_type_name or "").strip().lower() == "возврат"


class CostBook:
    """Себестоимость, действовавшая на дату продажи (история из таблицы себестоимости)."""

    def __init__(self, s: Session):
        self._dates: dict[int, list[date]] = defaultdict(list)
        self._costs: dict[int, list[Decimal]] = defaultdict(list)
        q = select(CostPrice).where(CostPrice.account_id == ACC).order_by(CostPrice.valid_from, CostPrice.id)
        for c in s.scalars(q):
            self._dates[c.nm_id].append(c.valid_from)
            self._costs[c.nm_id].append(c.cost)

    def on(self, nm_id: int | None, d: date | None) -> Decimal | None:
        dates = self._dates.get(nm_id or 0)
        if not dates:
            return None
        i = bisect.bisect_right(dates, d or date.max) - 1
        # продажа раньше первой введённой себестоимости — берём первую, иначе маржа будет завышена
        return self._costs[nm_id][max(i, 0)]


@dataclass
class Agg:
    sales_qty: int = 0
    returns_qty: int = 0
    retail_sales: Decimal = ZERO  # продажи − возвраты с СПП
    supplier_sales: Decimal = ZERO  # продажи − возвраты в цене продавца
    payout: Decimal = ZERO  # к перечислению за продажи − возвраты
    compensations: Decimal = ZERO  # прочие начисления к перечислению (компенсации, коррекции)
    loyalty_comp: Decimal = ZERO
    loyalty_points: Decimal = ZERO
    loyalty_fee: Decimal = ZERO
    deliveries: int = 0
    return_deliveries: int = 0
    logistics: Decimal = ZERO
    rebill: Decimal = ZERO
    storage: Decimal = ZERO
    acceptance: Decimal = ZERO
    penalties: Decimal = ZERO
    deductions: Decimal = ZERO
    additional: Decimal = ZERO
    acquiring: Decimal = ZERO
    advertising: Decimal = ZERO  # из статистики рекламы, только в детализации по артикулам
    cost: Decimal = ZERO
    cost_missing_qty: int = 0

    def add(self, r: ReportRow, costs: CostBook) -> None:
        op = _oper(r)
        sign = -1 if _is_return(r) else 1
        if op in ("продажа", "возврат"):
            qty = r.quantity or 0
            if sign > 0:
                self.sales_qty += qty
            else:
                self.returns_qty += qty
            self.retail_sales += sign * r.retail_amount
            self.supplier_sales += sign * r.retail_price_withdisc_rub * qty
            self.payout += sign * r.ppvz_for_pay
            cost = costs.on(r.nm_id, r.rr_dt)
            if cost is None:
                self.cost_missing_qty += qty
            else:
                self.cost += sign * cost * qty
        else:
            self.compensations += sign * r.ppvz_for_pay
        # программа лояльности — отдельные поля строки (cashback_*), а не отдельные операции
        self.loyalty_points += r.cashback_amount or ZERO
        self.loyalty_comp += r.cashback_discount or ZERO
        self.loyalty_fee += r.cashback_commission_change or ZERO
        self.deductions += r.deduction
        self.additional += r.additional_payment
        self.deliveries += r.delivery_amount or 0
        self.return_deliveries += r.return_amount or 0
        self.logistics += r.delivery_rub
        self.rebill += r.rebill_logistic_cost or ZERO
        self.storage += r.storage_fee
        self.acceptance += r.acceptance
        self.penalties += r.penalty
        self.acquiring += r.acquiring_fee

    def merge(self, other: Agg) -> None:
        for f in fields(self):
            setattr(self, f.name, getattr(self, f.name) + getattr(other, f.name))

    @property
    def net_qty(self) -> int:
        return self.sales_qty - self.returns_qty

    def result(self, tax_pct: Decimal) -> dict:
        tax = self.supplier_sales * tax_pct / 100
        totals = ReportTotals(
            net_qty=self.net_qty,
            supplier_sales=self.supplier_sales,
            payout_sales=self.payout + self.additional,
            logistics=self.logistics,
            storage=self.storage,
            acceptance=self.acceptance,
            penalties=self.penalties,
            other_wb=self.deductions,
            advertising=self.advertising,
            loyalty_compensation=self.loyalty_comp,
            loyalty_points=self.loyalty_points,
            loyalty_fee=self.loyalty_fee,
            tax=tax,
            cost=self.cost,
        )
        res = calculate_report(totals)
        out = {f.name: getattr(self, f.name) for f in fields(self)}
        out.update(
            net_qty=self.net_qty,
            tax=tax,
            profit=res.profit,
            roi_pct=res.roi_pct,
            margin_pct=res.margin_pct,
            profit_per_unit=res.profit_per_unit,
            logistics_per_unit=res.logistics_per_unit,
            buyout_pct=Decimal(self.net_qty) / self.deliveries * 100 if self.deliveries else None,
        )
        return out


def _rows(s: Session, date_from: date, date_to: date) -> list[ReportRow]:
    q = (
        select(ReportRow)
        .where(ReportRow.account_id == ACC, ReportRow.rr_dt >= date_from, ReportRow.rr_dt <= date_to)
        .order_by(ReportRow.rr_dt, ReportRow.rrd_id)
    )
    return list(s.scalars(q))


def _tax_pct(s: Session) -> Decimal:
    return Decimal(get_settings(s).get("tax_pct") or 0)


# --- 1. Анализ детализации (по товарам, размерам, складам) ---

GROUPS = {
    "nm": ("по артикулам", ("nm_id",)),
    "nm_size": ("по артикулам и размерам", ("nm_id", "ts_name")),
    "office": ("по складам", ("office_name",)),
    "office_nm_size": ("по складам, артикулам и размерам", ("office_name", "nm_id", "ts_name")),
}

KEY_COLUMNS = {
    "office_name": Column("office_name", "Склад", "text"),
    "nm_id": Column("nm_id", "Артикул WB", "text"),
    "ts_name": Column("ts_name", "Размер", "text"),
}

DETAIL_COLUMNS = [
    Column("sales_qty", "Продажи, шт", "int"),
    Column("returns_qty", "Возвраты, шт", "int"),
    Column("net_qty", "Продажи − возвраты, шт", "int"),
    Column("buyout_pct", "Выкуп, %", "pct"),
    Column("retail_sales", "Продажи с СПП, руб"),
    Column("supplier_sales", "Продажи в цене продавца, руб"),
    Column("payout", "К перечислению, руб"),
    Column("compensations", "Компенсации и коррекции, руб"),
    Column("logistics", "Логистика, руб"),
    Column("logistics_per_unit", "Логистика на ед., руб"),
    Column("storage", "Хранение, руб"),
    Column("acceptance", "Платная приёмка, руб"),
    Column("penalties", "Штрафы, руб"),
    Column("deductions", "Прочие удержания, руб"),
    Column("additional", "Доплаты, руб"),
    Column("loyalty_comp", "Компенсация по лояльности, руб"),
    Column("loyalty_points", "Баллы лояльности, руб"),
    Column("loyalty_fee", "Участие в лояльности, руб"),
    Column("acquiring", "Эквайринг, руб"),
    Column("advertising", "Реклама, руб"),
    Column("tax", "Налог, руб"),
    Column("cost", "Себестоимость, руб"),
    Column("profit", "Маржа, руб"),
    Column("profit_per_unit", "Маржа на ед., руб"),
    Column("roi_pct", "ROI, %", "pct"),
    Column("margin_pct", "Маржинальность, %", "pct"),
]


def detail(s: Session, date_from: date, date_to: date, group: str = "nm") -> Table:
    title, keys = GROUPS.get(group, GROUPS["nm"])
    costs = CostBook(s)
    groups: dict[tuple, Agg] = defaultdict(Agg)
    info: dict[int, tuple[str | None, str | None]] = {}
    for r in _rows(s, date_from, date_to):
        values = {"nm_id": r.nm_id or NO_NM, "ts_name": r.ts_name or "", "office_name": r.office_name or "—"}
        groups[tuple(values[k] for k in keys)].add(r, costs)
        if r.nm_id and (r.sa_name or r.subject_name):
            info[r.nm_id] = (r.sa_name, r.subject_name)
    ad_spend = ad_spend_by_nm(s, date_from, date_to) if keys == ("nm_id",) else {}
    for nm, spend in ad_spend.items():
        groups[(nm or NO_NM,)].advertising += spend

    tax_pct = _tax_pct(s)
    total = Agg()
    rows = []
    missing_cost = 0
    for key, agg in groups.items():
        total.merge(agg)
        row = dict(zip(keys, key, strict=True)) | agg.result(tax_pct)
        if "nm_id" in keys:
            row["sa_name"], row["subject_name"] = info.get(row["nm_id"], (None, None))
        missing_cost += agg.cost_missing_qty
        rows.append(row)
    rows.sort(key=lambda r: r["profit"], reverse=True)

    columns = [KEY_COLUMNS[k] for k in keys]
    if "nm_id" in keys:
        i = columns.index(KEY_COLUMNS["nm_id"]) + 1
        columns[i:i] = [Column("sa_name", "Артикул продавца", "text"), Column("subject_name", "Предмет", "text")]
    totals = {keys[0]: "Итого"} | total.result(tax_pct)
    notes = [f"Налог {tax_pct}% от продаж в цене продавца."]
    if keys == ("nm_id",):
        notes.append("Реклама — затраты из статистики кампаний за эти даты (загрузите рекламу из WB).")
    else:
        notes.append("Реклама вычитается только в детализации по артикулам: по складам и размерам WB её не делит.")
    if missing_cost:
        notes.append(f"Нет себестоимости для {missing_cost} шт. проданного: маржа по ним завышена.")
    return Table(f"Детализация {title}", columns + DETAIL_COLUMNS, rows, totals, notes)


# --- 2. Список недельных отчётов ---


def weeks(s: Session, date_from: date, date_to: date) -> Table:
    costs = CostBook(s)
    groups: dict[int, Agg] = defaultdict(Agg)
    periods: dict[int, tuple[date | None, date | None]] = {}
    lines: dict[int, int] = defaultdict(int)
    for r in _rows(s, date_from, date_to):
        rid = r.report_id or 0
        groups[rid].add(r, costs)
        periods.setdefault(rid, (r.date_from, r.date_to))
        lines[rid] += 1
    tax_pct = _tax_pct(s)
    headers = {h.report_id: h for h in s.scalars(select(SalesReport).where(SalesReport.account_id == ACC))}
    rows, total = [], Agg()
    wb_total = ZERO
    for rid, agg in groups.items():
        total.merge(agg)
        res = agg.result(tax_pct)
        to_pay = _to_pay(agg)
        head = headers.get(rid)
        if head:
            wb_total += head.bank_payment
        rows.append(
            {
                "report_id": str(rid),
                "date_from": periods[rid][0],
                "date_to": periods[rid][1],
                "lines": lines[rid],
                **res,
                "to_pay": to_pay,
                "wb_to_pay": head.bank_payment if head else None,
                "diff": to_pay - head.bank_payment if head else None,
            }
        )
    rows.sort(key=lambda r: (r["date_to"] or date.min, r["report_id"]), reverse=True)
    columns = [
        Column("report_id", "Номер отчёта", "text"),
        Column("date_from", "С", "date"),
        Column("date_to", "По", "date"),
        Column("lines", "Строк", "int"),
        Column("net_qty", "Продажи − возвраты, шт", "int"),
        Column("retail_sales", "Продажи с СПП, руб"),
        Column("payout", "К перечислению, руб"),
        Column("compensations", "Компенсации и коррекции, руб"),
        Column("logistics", "Логистика, руб"),
        Column("storage", "Хранение, руб"),
        Column("acceptance", "Платная приёмка, руб"),
        Column("penalties", "Штрафы, руб"),
        Column("deductions", "Прочие удержания, руб"),
        Column("additional", "Доплаты, руб"),
        Column("to_pay", "Итого к оплате (расчёт), руб"),
        Column("wb_to_pay", "Итого к оплате по шапке WB, руб"),
        Column("diff", "Разница, руб"),
        Column("cost", "Себестоимость, руб"),
        Column("profit", "Маржа, руб"),
    ]
    totals = {"report_id": "Итого", **total.result(tax_pct), "to_pay": _to_pay(total), "lines": sum(lines.values())}
    if headers:
        totals |= {"wb_to_pay": wb_total, "diff": None}
    notes = [
        "«Итого к оплате (расчёт)» сложено из строк детализации, «по шапке WB» — сумма из самого отчёта. "
        "Пустая шапка — у ключа нет категории «Финансы»."
    ]
    return Table("Недельные отчёты", columns, rows, totals, notes)


def _to_pay(a: Agg) -> Decimal:
    loyalty = a.loyalty_comp - a.loyalty_points - a.loyalty_fee
    return (
        a.payout
        + a.compensations
        + loyalty
        + a.additional
        - a.logistics
        - a.storage
        - a.acceptance
        - a.penalties
        - a.deductions
    )


# --- 3. Логистика ---


def logistics(s: Session, date_from: date, date_to: date, group: str = "nm") -> Table:
    by_office = group == "office"
    costs = CostBook(s)
    groups: dict[object, Agg] = defaultdict(Agg)
    info: dict[int, str | None] = {}
    for r in _rows(s, date_from, date_to):
        groups[(r.office_name or "—") if by_office else (r.nm_id or NO_NM)].add(r, costs)
        if r.nm_id and r.sa_name:
            info[r.nm_id] = r.sa_name
    tax_pct = _tax_pct(s)
    rows, total = [], Agg()
    for key, agg in groups.items():
        total.merge(agg)
        res = agg.result(tax_pct)
        row = {"key": key, "sa_name": None if by_office else info.get(key), **res}
        row["logistics_share"] = agg.logistics / agg.supplier_sales * 100 if agg.supplier_sales > 0 else None
        rows.append(row)
    rows.sort(key=lambda r: r["logistics"], reverse=True)
    columns = [Column("key", "Склад" if by_office else "Артикул WB", "text")]
    if not by_office:
        columns.append(Column("sa_name", "Артикул продавца", "text"))
    columns += [
        Column("deliveries", "Доставок к клиенту", "int"),
        Column("return_deliveries", "Доставок обратно", "int"),
        Column("net_qty", "Продажи − возвраты, шт", "int"),
        Column("buyout_pct", "Выкуп, %", "pct"),
        Column("logistics", "Логистика, руб"),
        Column("logistics_per_unit", "Логистика на проданную ед., руб"),
        Column("rebill", "Возмещение издержек по перевозке, руб"),
        Column("logistics_share", "Доля логистики в продажах, %", "pct"),
    ]
    totals = {"key": "Итого", **total.result(tax_pct)}
    totals["logistics_share"] = total.logistics / total.supplier_sales * 100 if total.supplier_sales > 0 else None
    title = "Логистика по складам" if by_office else "Логистика по артикулам"
    return Table(title, columns, rows, totals)


# --- 4. Штрафы и брак, 5. Прочие удержания ---


def _list_table(title: str, rows: list[ReportRow], amount, notes: list[str]) -> Table:
    out = []
    total = ZERO
    for r in rows:
        a = amount(r)
        total += a
        out.append(
            {
                "rr_dt": r.rr_dt,
                "report_id": str(r.report_id or ""),
                "nm_id": r.nm_id or "",
                "sa_name": r.sa_name,
                "office_name": r.office_name,
                "oper": r.supplier_oper_name,
                "reason": r.bonus_type_name,
                "amount": a,
            }
        )
    out.sort(key=lambda r: (r["rr_dt"] or date.min), reverse=True)
    columns = [
        Column("rr_dt", "Дата", "date"),
        Column("report_id", "Номер отчёта", "text"),
        Column("nm_id", "Артикул WB", "text"),
        Column("sa_name", "Артикул продавца", "text"),
        Column("office_name", "Склад", "text"),
        Column("oper", "Операция", "text"),
        Column("reason", "Причина", "text"),
        Column("amount", "Сумма, руб"),
    ]
    return Table(title, columns, out, {"rr_dt": "Итого", "amount": total}, notes)


def penalties(s: Session, date_from: date, date_to: date) -> Table:
    def is_penalty(r: ReportRow) -> bool:
        op = _oper(r)
        return bool(r.penalty) or "штраф" in op or "брак" in op

    def amount(r: ReportRow) -> Decimal:
        return r.penalty if r.penalty else (r.ppvz_for_pay or r.deduction)

    rows = [r for r in _rows(s, date_from, date_to) if is_penalty(r)]
    notes = ["Штрафы — это сумма удержания. Для строк про брак без штрафа показана сумма к перечислению (компенсация)."]
    return _list_table("Штрафы и брак", rows, amount, notes)


def deductions(s: Session, date_from: date, date_to: date) -> Table:
    rows = [r for r in _rows(s, date_from, date_to) if r.deduction]
    notes = ["Сюда входят и списания за рекламу, если WB удерживает их из отчёта. Отдельно реклама будет на этапе 4."]
    return _list_table("Прочие удержания", rows, lambda r: r.deduction, notes)


REPORTS = {
    "detail": detail,
    "weeks": weeks,
    "logistics": logistics,
    "penalties": penalties,
    "deductions": deductions,
}
