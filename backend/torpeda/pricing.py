"""Отправка цен в WB: предпросмотр → подтверждение → отправка → журнал → возврат.

Предпросмотр возвращает confirm_token — отпечаток списка «было → станет».
Отправка принимает тот же список и токен. Если цены в базе изменились
между предпросмотром и подтверждением, токен не совпадёт и отправки не будет.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from torpeda.calc import calculate
from torpeda.db import DEFAULT_ACCOUNT_ID
from torpeda.db.models import Price, PriceChange, Product
from torpeda.services import _result_dict, load_context, promo_options, unit_input
from torpeda.wb_api.client import WBClient, WBError

ACC = DEFAULT_ACCOUNT_ID


class PricingError(Exception):
    pass


@dataclass(frozen=True)
class Change:
    nm_id: int
    old_price: int
    old_discount: int
    new_price: int
    new_discount: int


def _int(v: Decimal) -> int:
    return int(v.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def confirm_token(changes: list[Change]) -> str:
    payload = json.dumps([c.__dict__ for c in sorted(changes, key=lambda c: c.nm_id)], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _preview(s: Session, changes: list[Change]) -> dict:
    ctx = load_context(s)
    items = []
    for c in changes:
        product = s.get(Product, (ACC, c.nm_id)) or Product(account_id=ACC, nm_id=c.nm_id)
        before, missing = unit_input(ctx, product, Decimal(c.old_price), Decimal(c.old_discount))
        after, _ = unit_input(ctx, product, Decimal(c.new_price), Decimal(c.new_discount))
        items.append(
            {
                **c.__dict__,
                "vendor_code": product.vendor_code,
                "before": _result_dict(ctx, calculate(before)),
                "after": _result_dict(ctx, calculate(after)),
                "missing": missing,
            }
        )
    return {"items": items, "confirm_token": confirm_token(changes)}


def changes_from_calc_prices(s: Session, nm_ids: list[int] | None = None) -> list[Change]:
    """Изменения из расчётных цен, введённых в таблице (все или выбранные товары)."""
    q = select(Price).where(Price.account_id == ACC, Price.calc_price.is_not(None))
    if nm_ids:
        q = q.where(Price.nm_id.in_(nm_ids))
    changes = []
    for p in s.scalars(q):
        new_discount = p.calc_discount_pct if p.calc_discount_pct is not None else p.discount_pct
        c = Change(p.nm_id, _int(p.price), _int(p.discount_pct), _int(p.calc_price), _int(new_discount))
        if (c.old_price, c.old_discount) != (c.new_price, c.new_discount):
            changes.append(c)
    return changes


def changes_from_promo(s: Session, nm_ids: list[int]) -> list[Change]:
    """Цена и скидка самой выгодной акции для выбранных артикулов (если в акцию ещё не вступили)."""
    ctx = load_context(s)
    products = {p.nm_id: p for p in s.scalars(select(Product).where(Product.account_id == ACC))}
    prices = {p.nm_id: p for p in s.scalars(select(Price).where(Price.account_id == ACC))}
    options = promo_options(s, ctx, products, datetime.now(), prices)
    changes = []
    for nm in nm_ids:
        best = options.get(nm, {}).get("best")
        cur = prices.get(nm)
        if cur is None or best is None or best["in_action"] or best["price"] is None or best["discount_pct"] is None:
            continue
        c = Change(nm, _int(cur.price), _int(cur.discount_pct), _int(best["price"]), _int(best["discount_pct"]))
        if (c.old_price, c.old_discount) != (c.new_price, c.new_discount):
            changes.append(c)
    return changes


def changes_for_revert(s: Session, change_ids: list[int]) -> list[Change]:
    """Вернуть цены, какими они были до выбранных отправок."""
    changes = []
    for log in s.scalars(select(PriceChange).where(PriceChange.id.in_(change_ids), PriceChange.status == "sent")):
        current = s.get(Price, (ACC, log.nm_id))
        if current is None:
            continue
        changes.append(
            Change(
                log.nm_id,
                _int(current.price),
                _int(current.discount_pct),
                _int(log.old_price),
                _int(log.old_discount_pct),
            )
        )
    return changes


def preview(s: Session, changes: list[Change]) -> dict:
    for c in changes:
        if c.new_price <= 0:
            raise PricingError(f"Артикул {c.nm_id}: цена должна быть больше нуля")
        if not 0 <= c.new_discount <= 99:
            raise PricingError(f"Артикул {c.nm_id}: скидка должна быть от 0 до 99%")
    return _preview(s, changes)


def send(s: Session, client: WBClient, changes: list[Change], token: str) -> dict:
    """Отправляет подтверждённые изменения. Вызывать только после предпросмотра."""
    if not changes:
        raise PricingError("Нечего отправлять")
    if token != confirm_token(changes):
        raise PricingError("Подтверждение не совпадает с предпросмотром. Откройте предпросмотр заново.")
    for c in changes:
        current = s.get(Price, (ACC, c.nm_id))
        if current is None or (_int(current.price), _int(current.discount_pct)) != (c.old_price, c.old_discount):
            raise PricingError(f"Цена артикула {c.nm_id} изменилась после предпросмотра. Откройте предпросмотр заново.")

    payload = [{"nmID": c.nm_id, "price": c.new_price, "discount": c.new_discount} for c in changes]
    try:
        task_id = client.upload_prices(payload)
        status, error = "sent", None
    except WBError as e:
        task_id, status, error = None, "error", str(e)

    logs = []
    for c in changes:
        log = PriceChange(
            account_id=ACC,
            nm_id=c.nm_id,
            old_price=Decimal(c.old_price),
            old_discount_pct=Decimal(c.old_discount),
            new_price=Decimal(c.new_price),
            new_discount_pct=Decimal(c.new_discount),
            wb_task_id=task_id,
            status=status,
            error=error,
        )
        s.add(log)
        logs.append(log)
        if status == "sent":
            price = s.get(Price, (ACC, c.nm_id))
            price.price = Decimal(c.new_price)
            price.discount_pct = Decimal(c.new_discount)
            price.calc_price = None
            price.calc_discount_pct = None
    s.commit()
    return {"status": status, "wb_task_id": task_id, "error": error, "change_ids": [log.id for log in logs]}


def history(s: Session, limit: int = 200) -> list[dict]:
    rows = s.scalars(
        select(PriceChange).where(PriceChange.account_id == ACC).order_by(PriceChange.id.desc()).limit(limit)
    )
    return [
        {
            "id": r.id,
            "nm_id": r.nm_id,
            "old_price": r.old_price,
            "old_discount_pct": r.old_discount_pct,
            "new_price": r.new_price,
            "new_discount_pct": r.new_discount_pct,
            "status": r.status,
            "error": r.error,
            "wb_task_id": r.wb_task_id,
            "sent_at": r.sent_at,
        }
        for r in rows
    ]
