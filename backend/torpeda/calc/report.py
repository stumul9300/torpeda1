"""Фактическая прибыль по еженедельным финансовым отчётам WB.

Формула сверена с отчётом «Ракеты» «Анализ детализации финансовых отчётов по складам
и размерам» (выгрузка от 23.10.2026): совпала до копейки во всех 9 892 строках
(склады, артикулы, размеры, итог). См. docs/formulas.md.

    Маржа = К перечислению (продажи − возвраты, без компенсаций)
          + компенсация скидки по программе лояльности
          − баллы, удержанные по программе лояльности
          − стоимость участия в программе лояльности
          − логистика − хранение − платная приёмка − штрафы
          − брак − прочие удержания WB − реклама − налог
          − себестоимость − прочие наши затраты
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .unit_economics import HUNDRED, ZERO


@dataclass(frozen=True)
class ReportTotals:
    """Суммы по товару (или складу, или всему кабинету) за период из финансовых отчётов."""

    net_qty: int  # продажи − возвраты, шт
    supplier_sales: Decimal  # продажи − возвраты в цене поставщика (до СПП), руб
    payout_sales: Decimal  # «к перечислению» за продажи − возвраты, без компенсаций, руб
    logistics: Decimal = ZERO
    storage: Decimal = ZERO
    acceptance: Decimal = ZERO  # платная приёмка
    penalties: Decimal = ZERO  # все штрафы
    defect: Decimal = ZERO  # брак по отчёту WB
    other_wb: Decimal = ZERO  # прочие удержания WB
    advertising: Decimal = ZERO
    loyalty_compensation: Decimal = ZERO  # компенсация скидки по программе лояльности (плюс)
    loyalty_points: Decimal = ZERO  # баллы, удержанные по программе лояльности (минус)
    loyalty_fee: Decimal = ZERO  # стоимость участия в программе лояльности (минус)
    tax: Decimal = ZERO
    cost: Decimal = ZERO  # себестоимость проданного
    own_expenses: Decimal = ZERO  # наш брак, прочие затраты, маркетинг


@dataclass(frozen=True)
class ReportResult:
    profit: Decimal
    roi_pct: Decimal | None  # от себестоимости
    margin_pct: Decimal | None  # от суммы продаж в цене поставщика
    profit_per_unit: Decimal | None
    logistics_per_unit: Decimal | None
    storage_per_unit: Decimal | None


def _per_unit(total: Decimal, qty: int) -> Decimal | None:
    return total / qty if qty > 0 else None


def calculate_report(t: ReportTotals) -> ReportResult:
    profit = (
        t.payout_sales
        + t.loyalty_compensation
        - t.loyalty_points
        - t.loyalty_fee
        - t.logistics
        - t.storage
        - t.acceptance
        - t.penalties
        - t.defect
        - t.other_wb
        - t.advertising
        - t.tax
        - t.cost
        - t.own_expenses
    )
    return ReportResult(
        profit=profit,
        roi_pct=profit / t.cost * HUNDRED if t.cost else None,
        margin_pct=profit / t.supplier_sales * HUNDRED if t.supplier_sales else None,
        profit_per_unit=_per_unit(profit, t.net_qty),
        logistics_per_unit=_per_unit(t.logistics, t.net_qty),
        storage_per_unit=_per_unit(t.storage, t.net_qty),
    )
