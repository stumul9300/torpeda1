"""Логистика и хранение на одну выкупленную единицу.

Основной способ (решение Ольги): по фактическим данным отчётов WB —
вся логистика товара за период, делённая на число выкупленных штук.
Для новых товаров без продаж — по тарифу и проценту выкупа.
"""

from __future__ import annotations

from decimal import Decimal

from .unit_economics import ZERO, pct


def from_report(total_logistics: Decimal, sold_units: int) -> Decimal | None:
    """Фактическая логистика на единицу: сумма логистики из отчётов / выкупленные штуки."""
    if sold_units <= 0:
        return None
    return total_logistics / sold_units


def tariff_forward(
    volume_l: Decimal, first_liter: Decimal, extra_liter: Decimal, coef: Decimal = Decimal(1)
) -> Decimal:
    """Логистика до покупателя по тарифу: (первый литр + доп. литр × (V − 1)) × коэффициент склада."""
    extra = volume_l - 1 if volume_l > 1 else ZERO
    return (first_liter + extra_liter * extra) * coef


def per_sold_unit(forward: Decimal, reverse: Decimal, buyout_pct: Decimal) -> Decimal | None:
    """Логистика на одну выкупленную единицу с учётом отказов.

    На одну продажу уходит 1/b отправок, из них (1 − b)/b возвращаются:
        L_eff = L / b + L_возв × (1 − b) / b
    """
    b = pct(buyout_pct)
    if b <= ZERO:
        return None
    return forward / b + reverse * (1 - b) / b


def storage_per_unit(per_day: Decimal, days: Decimal) -> Decimal:
    """Хранение на единицу: ставка в день × число дней на складе до продажи."""
    return per_day * days
