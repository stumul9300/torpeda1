"""Сборка строк таблицы товаров и анализа акций из базы + расчётный модуль."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from torpeda.calc import Scheme, UnitInput, UnitResult, calculate
from torpeda.db import DEFAULT_ACCOUNT_ID
from torpeda.db.models import (
    CommissionRate,
    CostPrice,
    Order,
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


def spp_from_orders(s: Session) -> dict[int, tuple[Decimal, datetime]]:
    """СПП из самого свежего заказа без отмены по каждому артикулу и время этого заказа.

    WB отдаёт СПП только в уже сделанных заказах: у товара без свежих заказов значения нет."""
    q = (
        select(Order.nm_id, Order.spp, Order.date)
        .where(Order.account_id == ACC, Order.is_cancel.is_(False), Order.spp.is_not(None))
        .order_by(Order.date)
    )
    return {nm: (spp, at) for nm, spp, at in s.execute(q)}


# Откуда брать СПП. Чтобы подключить более точный источник, достаточно заменить функцию:
# она получает сессию и возвращает {артикул: (СПП в %, время значения)}.
SPP_SOURCE = spp_from_orders


def _promo_advice(entry: dict, cur: Price | None, plan_seller: Decimal) -> dict:
    """Что делать, чтобы вступить в акцию: какую скидку поставить, на сколько это снизит цену, что будет с маржой."""
    cur_seller = (cur.price * (1 - cur.discount_pct / 100)).quantize(Decimal("0.01")) if cur else None
    extra: dict = {"cur_seller_price": cur_seller, "plan_seller_price": plan_seller.quantize(Decimal("0.01"))}
    if entry["in_action"]:
        extra["advice"] = "уже участвует в акции"
        return extra
    if cur_seller is None:
        extra["advice"] = "нет текущей цены из WB"
        return extra
    delta = plan_seller - cur_seller  # цена продавца для акции минус нынешняя
    extra["delta_seller"] = delta.quantize(Decimal("0.01"))
    extra["delta_pct"] = (delta / cur_seller * 100).quantize(Decimal("0.01")) if cur_seller else None
    if delta >= 0:
        extra["advice"] = "цена уже подходит: можно вступать без снижения"
        return extra
    loss = ", убыток" if entry["status"] == "loss" else ""
    extra["advice"] = (
        f"понизить цену продавца до {extra['plan_seller_price']:.2f} ₽ "
        f"(на {-extra['delta_seller']:.2f} ₽, {-extra['delta_pct']:.2f}%), маржа {entry['profit']} ₽{loss}"
    )
    return extra


def promo_options(
    s: Session, ctx: Context, products: dict[int, Product], now: datetime, prices: dict[int, Price] | None = None
) -> dict[int, dict]:
    """Для каждого артикула: акция, в которой он участвует сейчас, и самая выгодная из ещё не закончившихся.

    Выгодная — с наибольшей ценой продавца после скидки среди акций без убытка."""
    all_promos = list(s.scalars(select(Promotion).where(Promotion.account_id == ACC)))
    file_names = {p.name for p in all_promos if p.id < 0}  # акции из файлов важнее одноимённых из API
    promos = {
        p.id: p for p in all_promos if (p.end_at is None or p.end_at >= now) and (p.id < 0 or p.name not in file_names)
    }
    out: dict[int, dict] = {}
    for it in s.scalars(select(PromotionItem).where(PromotionItem.account_id == ACC)):
        promo, product = promos.get(it.promotion_id), products.get(it.nm_id)
        if promo is None or product is None:
            continue
        info = out.setdefault(it.nm_id, {"current": None, "best": None, "all": []})
        started = promo.start_at is None or promo.start_at <= now
        if it.in_action and started:
            info["current"] = promo.name
        if it.plan_price is None:
            continue
        inp, _ = unit_input(ctx, product, it.plan_price, it.plan_discount_pct or ZERO)
        res = calculate(inp)
        entry = {
            "name": promo.name,
            "type": promo.type,
            "end_at": promo.end_at,
            "in_action": it.in_action,
            "price": it.plan_price,  # цена до скидки, которую надо поставить, чтобы вступить в акцию
            "discount_pct": it.plan_discount_pct,
            **_result_dict(ctx, res),
        }
        entry.update(_promo_advice(entry, (prices or {}).get(it.nm_id), res.seller_price))
        info["all"].append(entry)
        # выгодная по цене: максимальная цена продавца после скидки, убыточные акции только если других нет
        key = (not res.is_loss, res.seller_price)
        best = info["best"]
        if best is None or key > best["_key"]:
            info["best"] = {"_key": key, **entry}
    for info in out.values():
        if info["best"]:
            info["best"].pop("_key")
    return out


def recalc_by_promos(s: Session) -> dict:
    """Новая цена по самой выгодной акции для каждого артикула (кроме убыточных и без себестоимости).

    Пишет в «Новую цену» цену и скидку акции, в WB ничего не уходит: отправка отдельно, с предпросмотром."""
    ctx = load_context(s)
    products = {p.nm_id: p for p in s.scalars(select(Product).where(Product.account_id == ACC))}
    prices = {p.nm_id: p for p in s.scalars(select(Price).where(Price.account_id == ACC))}
    result = {"changed": 0, "loss": 0, "no_cost": 0, "no_promo": 0}
    options = promo_options(s, ctx, products, datetime.now(), prices)
    for nm, price in prices.items():
        best = options.get(nm, {}).get("best")
        if best is None:
            result["no_promo"] += 1
        elif nm not in ctx.costs:
            result["no_cost"] += 1
        elif best["status"] == "loss":
            result["loss"] += 1
        else:
            price.calc_price = best["price"]
            price.calc_discount_pct = best["discount_pct"] if best["discount_pct"] is not None else ZERO
            result["changed"] += 1
    s.commit()
    return result


def _promo_note(any_promos: bool, info: dict | None, any_files: bool = True) -> str | None:
    """Почему по артикулу нет цены для вступления в акцию. Если цена есть, пояснение не нужно."""
    if info and info.get("best"):
        return None
    if not any_promos:
        return "акции не загружены: нажмите «Загрузить из WB»"
    if info and info.get("current"):
        return f"участвует в «{info['current']}», плановой цены от WB нет"
    if not any_files:
        return "WB по API акций не предлагает; автоакции берутся из файлов: «Акции» → «Загрузить акции из файлов»"
    return "нет ни в акциях из WB, ни в загруженных файлах акций (WB не предлагает этому товару действующих акций)"


def product_rows(s: Session) -> list[dict]:
    ctx = load_context(s)
    spp = SPP_SOURCE(s)
    prices = {p.nm_id: p for p in s.scalars(select(Price).where(Price.account_id == ACC))}
    stocks = {
        (nm, scheme): qty
        for nm, scheme, qty in s.execute(
            select(Stock.nm_id, Stock.scheme, func.sum(Stock.quantity))
            .where(Stock.account_id == ACC)
            .group_by(Stock.nm_id, Stock.scheme)
        )
    }
    all_products = list(s.scalars(select(Product).where(Product.account_id == ACC).order_by(Product.nm_id)))
    now = datetime.now()
    promos = promo_options(s, ctx, {p.nm_id: p for p in all_products}, now, prices)
    any_promos = bool(
        s.scalar(
            select(func.count())
            .select_from(Promotion)
            .where(Promotion.account_id == ACC, (Promotion.end_at.is_(None)) | (Promotion.end_at >= now))
        )
    )
    any_files = bool(
        s.scalar(select(func.count()).select_from(Promotion).where(Promotion.account_id == ACC, Promotion.id < 0))
    )
    rows = []
    for p in all_products:
        price = prices.get(p.nm_id)
        row = {
            "nm_id": p.nm_id,
            "photo": f"/api/photos/{p.nm_id}" if p.photo_url else None,
            "vendor_code": p.vendor_code,
            "title": p.title,
            "brand": p.brand,
            "subject": p.subject_name,
            "stock_fbo": int(stocks.get((p.nm_id, "FBO")) or 0),
            "stock_fbs": int(stocks.get((p.nm_id, "FBS")) or 0),
            "sold_net_qty": ctx.facts.get(p.nm_id, ReportFacts()).net_qty,
            "cost": ctx.costs.get(p.nm_id),
            "price": price.price if price else None,
            "discount_pct": price.discount_pct if price else None,
            "site_price": price.site_price if price else None,
            "site_price_at": price.site_price_at if price else None,
            "spp": spp[p.nm_id][0] if p.nm_id in spp else None,
            "spp_at": spp[p.nm_id][1] if p.nm_id in spp else None,
            "calc_price": price.calc_price if price else None,
            "calc_discount_pct": price.calc_discount_pct if price else None,
            "current": None,
            "calc": None,
            "promo_current": promos.get(p.nm_id, {}).get("current"),
            "promo_best": promos.get(p.nm_id, {}).get("best"),
            "promos": promos.get(p.nm_id, {}).get("all", []),
            "promo_note": _promo_note(any_promos, promos.get(p.nm_id), any_files),
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
        # plan_price — цена до скидки, plan_discount_pct — скидка для вступления (см. sync._plan_before_discount).
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
