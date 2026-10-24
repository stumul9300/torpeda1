"""Сборка строк таблицы товаров и анализа акций из базы + расчётный модуль."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from torpeda.calc import Scheme, UnitInput, UnitResult, calculate
from torpeda.db import DEFAULT_ACCOUNT_ID
from torpeda.db.models import (
    CommissionRate,
    CostPrice,
    Price,
    Product,
    Promotion,
    PromotionItem,
    ReportRow,
    Setting,
    Stock,
)

ACC = DEFAULT_ACCOUNT_ID
ZERO = Decimal(0)


def get_settings(s: Session) -> dict[str, str]:
    return {r.key: r.value for r in s.scalars(select(Setting).where(Setting.account_id == ACC))}


@dataclass
class ReportFacts:
    """Факт по отчётам за период для одного товара."""

    net_qty: int = 0
    logistics: Decimal = ZERO
    storage: Decimal = ZERO
    acquiring: Decimal = ZERO
    seller_sales: Decimal = ZERO  # продажи в цене продавца, для доли эквайринга

    @property
    def logistics_per_unit(self) -> Decimal | None:
        return self.logistics / self.net_qty if self.net_qty > 0 else None

    @property
    def storage_per_unit(self) -> Decimal | None:
        return self.storage / self.net_qty if self.net_qty > 0 else None


def report_facts(s: Session, since: date) -> dict[int, ReportFacts]:
    facts: dict[int, ReportFacts] = {}
    rows = s.scalars(
        select(ReportRow).where(ReportRow.account_id == ACC, ReportRow.rr_dt >= since, ReportRow.nm_id.is_not(None))
    )
    for r in rows:
        f = facts.setdefault(r.nm_id, ReportFacts())
        if r.supplier_oper_name == "Продажа":
            f.net_qty += r.quantity
            f.seller_sales += r.retail_price_withdisc_rub * r.quantity
        elif r.supplier_oper_name == "Возврат":
            f.net_qty -= r.quantity
            f.seller_sales -= r.retail_price_withdisc_rub * r.quantity
        f.logistics += r.delivery_rub
        f.storage += r.storage_fee
        f.acquiring += r.acquiring_fee
    return facts


def current_costs(s: Session, on: date) -> dict[int, Decimal]:
    """Последняя введённая себестоимость, действующая на дату."""
    latest = (
        select(CostPrice.nm_id, func.max(CostPrice.id).label("id"))
        .where(CostPrice.account_id == ACC, CostPrice.valid_from <= on)
        .group_by(CostPrice.nm_id)
        .subquery()
    )
    rows = s.execute(select(CostPrice.nm_id, CostPrice.cost).join(latest, CostPrice.id == latest.c.id))
    return {nm: cost for nm, cost in rows}


def _acquiring_pct(settings: dict[str, str], facts: dict[int, ReportFacts]) -> Decimal:
    if settings.get("acquiring_pct"):
        return Decimal(settings["acquiring_pct"])
    total_fee = sum((f.acquiring for f in facts.values()), ZERO)
    total_sales = sum((f.seller_sales for f in facts.values()), ZERO)
    return total_fee / total_sales * 100 if total_sales > 0 else ZERO


@dataclass
class Context:
    settings: dict[str, str]
    scheme: Scheme
    tax_pct: Decimal
    acquiring_pct: Decimal
    risk_margin_pct: Decimal
    facts: dict[int, ReportFacts]
    costs: dict[int, Decimal]
    commissions: dict[int, CommissionRate]


def load_context(s: Session, today: date | None = None) -> Context:
    today = today or date.today()
    settings = get_settings(s)
    days = int(settings.get("report_days") or 30)
    facts = report_facts(s, today - timedelta(days=days))
    return Context(
        settings=settings,
        scheme=Scheme(settings.get("scheme") or "FBO"),
        tax_pct=Decimal(settings.get("tax_pct") or 0),
        acquiring_pct=_acquiring_pct(settings, facts),
        risk_margin_pct=Decimal(settings.get("risk_margin_pct") or 10),
        facts=facts,
        costs=current_costs(s, today),
        commissions={c.subject_id: c for c in s.scalars(select(CommissionRate))},
    )


def unit_input(ctx: Context, product: Product, price: Decimal, discount_pct: Decimal) -> tuple[UnitInput, list[str]]:
    """Собирает данные для расчёта. Второе значение — чего не хватает для точного расчёта."""
    missing = []
    cost = ctx.costs.get(product.nm_id)
    if cost is None:
        missing.append("себестоимость")
    rate = ctx.commissions.get(product.subject_id)
    if rate is None:
        missing.append("комиссия")
    f = ctx.facts.get(product.nm_id, ReportFacts())
    logistics = f.logistics_per_unit
    if logistics is None:
        missing.append("логистика (нет продаж за период)")
    inp = UnitInput(
        price_before_discount=price,
        discount_pct=discount_pct,
        cost=cost or ZERO,
        commission_pct=(rate.fbo_pct if ctx.scheme is Scheme.FBO else rate.fbs_pct) if rate else ZERO,
        logistics_per_unit=logistics or ZERO,
        acquiring_pct=ctx.acquiring_pct,
        tax_pct=ctx.tax_pct,
        storage_per_unit=f.storage_per_unit or ZERO,
    )
    return inp, missing


def status(ctx: Context, r: UnitResult) -> str:
    if r.is_loss:
        return "loss"
    if r.margin_pct is not None and r.margin_pct < ctx.risk_margin_pct:
        return "risk"
    return "ok"


def _result_dict(ctx: Context, r: UnitResult) -> dict:
    rr = r.rounded()
    return {**rr.__dict__, "status": status(ctx, r)}


def product_rows(s: Session) -> list[dict]:
    ctx = load_context(s)
    prices = {p.nm_id: p for p in s.scalars(select(Price).where(Price.account_id == ACC))}
    stocks = {
        nm: qty
        for nm, qty in s.execute(
            select(Stock.nm_id, func.sum(Stock.quantity)).where(Stock.account_id == ACC).group_by(Stock.nm_id)
        )
    }
    rows = []
    for p in s.scalars(select(Product).where(Product.account_id == ACC).order_by(Product.nm_id)):
        price = prices.get(p.nm_id)
        row = {
            "nm_id": p.nm_id,
            "vendor_code": p.vendor_code,
            "title": p.title,
            "brand": p.brand,
            "subject": p.subject_name,
            "stock_fbo": int(stocks.get(p.nm_id) or 0),
            "sold_net_qty": ctx.facts.get(p.nm_id, ReportFacts()).net_qty,
            "cost": ctx.costs.get(p.nm_id),
            "price": price.price if price else None,
            "discount_pct": price.discount_pct if price else None,
            "calc_price": price.calc_price if price else None,
            "calc_discount_pct": price.calc_discount_pct if price else None,
            "current": None,
            "calc": None,
            "missing": [],
        }
        if price:
            inp, missing = unit_input(ctx, p, price.price, price.discount_pct)
            row["current"] = _result_dict(ctx, calculate(inp))
            row["missing"] = missing
            if price.calc_price is not None:
                calc_disc = price.calc_discount_pct if price.calc_discount_pct is not None else price.discount_pct
                inp_calc, _ = unit_input(ctx, p, price.calc_price, calc_disc)
                row["calc"] = _result_dict(ctx, calculate(inp_calc))
        else:
            row["missing"] = ["цена"]
        rows.append(row)
    return rows


def promotion_rows(s: Session, promotion_id: int) -> dict | None:
    promo = s.get(Promotion, (ACC, promotion_id))
    if promo is None:
        return None
    ctx = load_context(s)
    products = {p.nm_id: p for p in s.scalars(select(Product).where(Product.account_id == ACC))}
    items = []
    for it in s.scalars(
        select(PromotionItem).where(PromotionItem.account_id == ACC, PromotionItem.promotion_id == promotion_id)
    ):
        product = products.get(it.nm_id) or Product(account_id=ACC, nm_id=it.nm_id)
        row = {"nm_id": it.nm_id, "vendor_code": product.vendor_code, "in_action": it.in_action}
        if it.price is not None:
            inp, missing = unit_input(ctx, product, it.price, it.discount_pct or ZERO)
            row["current"] = _result_dict(ctx, calculate(inp))
            row["missing"] = missing
        # Считаем, что planPrice — цена до скидки для акции, а planDiscount — скидка на неё.
        # Проверить на реальных данных WB после первой загрузки.
        if it.plan_price is not None:
            inp, missing = unit_input(ctx, product, it.plan_price, it.plan_discount_pct or ZERO)
            promo_result = calculate(inp)
            row["promo"] = _result_dict(ctx, promo_result)
            row["missing"] = missing
            row["recommend"] = "участвовать" if status(ctx, promo_result) == "ok" else "не участвовать"
        items.append(row)
    return {
        "id": promo.id,
        "name": promo.name,
        "start_at": promo.start_at,
        "end_at": promo.end_at,
        "items": items,
    }
