"""Юнит-экономика товара Wildberries: прибыль, ROI и маржинальность на одну проданную единицу.

Все суммы в рублях, все проценты в виде чисел от 0 до 100 (40 = 40%).
Модуль считает в Decimal без промежуточных округлений; округление до копеек
делается только при показе (см. UnitResult.rounded).

Формула сверена с калькулятором «Ракеты» (см. docs/formulas.md):

    P      = P0 × (1 − d)                        цена продавца
    Комиссия   = P × k
    Эквайринг  = P × a
    Налог      = P × t
    Прибыль    = P − Комиссия − Эквайринг − Налог − Логистика − Реклама − Хранение − Брак − Себестоимость
    ROI, %     = Прибыль / Себестоимость × 100
    Маржа, %   = Прибыль / P × 100
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

ZERO = Decimal(0)
HUNDRED = Decimal(100)
KOPECK = Decimal("0.01")
RUBLE = Decimal(1)


class Scheme(StrEnum):
    FBO = "FBO"  # товар на складе WB
    FBS = "FBS"  # товар на складе продавца


def D(value: Decimal | float | str) -> Decimal:
    """Приводит число к Decimal. float идёт через str, чтобы 0.1 не стал 0.1000000000000000055."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


def pct(value: Decimal) -> Decimal:
    """40 -> 0.40"""
    return value / HUNDRED


def round_money(value: Decimal) -> Decimal:
    return value.quantize(KOPECK, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CommissionRates:
    """Комиссия WB по предмету, отдельно для FBO и FBS, в процентах."""

    fbo_pct: Decimal
    fbs_pct: Decimal

    def for_scheme(self, scheme: Scheme) -> Decimal:
        return self.fbo_pct if scheme is Scheme.FBO else self.fbs_pct


@dataclass(frozen=True)
class UnitInput:
    """Исходные данные для расчёта одной единицы товара."""

    price_before_discount: Decimal  # P0, цена до скидки
    discount_pct: Decimal  # d, скидка продавца
    cost: Decimal  # себестоимость (закупка + доп. расходы)
    commission_pct: Decimal  # k, комиссия WB для выбранной схемы
    logistics_per_unit: Decimal  # логистика на одну выкупленную единицу (см. logistics.py)
    acquiring_pct: Decimal = ZERO  # a, эквайринг
    tax_pct: Decimal = ZERO  # t, налог с суммы продажи
    advertising_per_unit: Decimal = ZERO
    storage_per_unit: Decimal = ZERO
    defect_per_unit: Decimal = ZERO  # брак
    spp_pct: Decimal = ZERO  # СПП: платит WB, на прибыль продавца не влияет, нужна для показа цены покупателю


@dataclass(frozen=True)
class UnitResult:
    seller_price: Decimal  # P, цена продавца со скидкой
    price_with_spp: Decimal  # цена для покупателя после СПП, в целых рублях
    commission: Decimal
    acquiring: Decimal
    tax: Decimal
    logistics: Decimal
    advertising: Decimal
    storage: Decimal
    defect: Decimal
    cost: Decimal
    profit: Decimal
    roi_pct: Decimal | None  # None, если себестоимость не задана
    margin_pct: Decimal | None  # None, если цена равна нулю

    @property
    def is_loss(self) -> bool:
        return self.profit < ZERO

    def rounded(self) -> UnitResult:
        """Копия с суммами и процентами, округлёнными до двух знаков."""
        values = {}
        for f in fields(self):
            v = getattr(self, f.name)
            values[f.name] = v if v is None or f.name == "price_with_spp" else round_money(v)
        return UnitResult(**values)


def seller_price(price_before_discount: Decimal, discount_pct: Decimal) -> Decimal:
    return price_before_discount * (1 - pct(discount_pct))


def calculate(inp: UnitInput) -> UnitResult:
    p = seller_price(inp.price_before_discount, inp.discount_pct)
    commission = p * pct(inp.commission_pct)
    acquiring = p * pct(inp.acquiring_pct)
    tax = p * pct(inp.tax_pct)

    profit = (
        p
        - commission
        - acquiring
        - tax
        - inp.logistics_per_unit
        - inp.advertising_per_unit
        - inp.storage_per_unit
        - inp.defect_per_unit
        - inp.cost
    )

    return UnitResult(
        seller_price=p,
        price_with_spp=(p * (1 - pct(inp.spp_pct))).quantize(RUBLE, rounding=ROUND_HALF_UP),
        commission=commission,
        acquiring=acquiring,
        tax=tax,
        logistics=inp.logistics_per_unit,
        advertising=inp.advertising_per_unit,
        storage=inp.storage_per_unit,
        defect=inp.defect_per_unit,
        cost=inp.cost,
        profit=profit,
        roi_pct=profit / inp.cost * HUNDRED if inp.cost else None,
        margin_pct=profit / p * HUNDRED if p else None,
    )


def price_for_target_margin(inp: UnitInput, target_margin_pct: Decimal) -> Decimal | None:
    """Цена продавца P, при которой маржинальность равна целевой.

    P = (С + логистика + реклама + хранение + брак) / (1 − k − a − t − m)
    Возвращает None, если процентные удержания вместе с целевой маржой съедают 100% цены.
    """
    fixed = inp.cost + inp.logistics_per_unit + inp.advertising_per_unit + inp.storage_per_unit + inp.defect_per_unit
    share = 1 - pct(inp.commission_pct) - pct(inp.acquiring_pct) - pct(inp.tax_pct) - pct(target_margin_pct)
    if share <= ZERO:
        return None
    return fixed / share


def price_before_discount_for(seller_price_value: Decimal, discount_pct: Decimal) -> Decimal | None:
    """Обратный пересчёт: какую цену до скидки поставить, чтобы при скидке d получить нужную цену продавца."""
    share = 1 - pct(discount_pct)
    if share <= ZERO:
        return None
    return seller_price_value / share
