"""Защита цен от автоакций WB: если WB сам понизил цену, вернуть её обратно (если Ольга это включила).

Понижения замечает sync_prices (PriceAlert). Возврат идёт через тот же pricing.send, что и обычная отправка,
поэтому попадает в «Журнал цен». Включается настройкой revert_autopromo, по умолчанию выключено.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from torpeda import pricing
from torpeda.db import DEFAULT_ACCOUNT_ID
from torpeda.db.models import Price, PriceAlert, Setting
from torpeda.wb_api.client import WBClient

ACC = DEFAULT_ACCOUNT_ID
MAX_REVERTS_PER_DAY = 3  # защита от зацикливания: WB снова понижает, мы снова возвращаем


def _setting(s: Session, key: str) -> str:
    row = s.get(Setting, (ACC, key))
    return row.value if row else ""


def enabled(s: Session) -> bool:
    return _setting(s, "revert_autopromo") == "1"


def excluded(s: Session) -> set[int]:
    return {int(x) for x in _setting(s, "revert_exclude").replace(";", ",").split(",") if x.strip().isdigit()}


def restored(s: Session, a: PriceAlert) -> bool:
    cur = s.get(Price, (ACC, a.nm_id))
    return cur is not None and (cur.price, cur.discount_pct) == (a.old_price, a.old_discount_pct)


def _change(s: Session, a: PriceAlert) -> pricing.Change | None:
    cur = s.get(Price, (ACC, a.nm_id))
    if cur is None or restored(s, a):
        return None
    return pricing.Change(
        a.nm_id,
        pricing._int(cur.price),
        pricing._int(cur.discount_pct),
        pricing._int(a.old_price),
        pricing._int(a.old_discount_pct),
    )


def changes_for_alerts(s: Session, alert_ids: list[int]) -> list[pricing.Change]:
    """Ручной возврат: цены, какими они были до выбранных изменений WB."""
    alerts = s.scalars(select(PriceAlert).where(PriceAlert.id.in_(alert_ids)))
    return [c for a in alerts if (c := _change(s, a)) is not None]


def revert_pending(s: Session, client: WBClient, now: datetime | None = None) -> dict:
    """Возвращает цены по новым оповещениям. Вызывать только при включённой настройке."""
    now = now or datetime.now(UTC).replace(tzinfo=None)
    skip = excluded(s)
    result = {"reverted": 0, "skipped": 0, "error": None}
    todo: list[tuple[PriceAlert, pricing.Change]] = []
    latest: dict[int, PriceAlert] = {}
    for a in s.scalars(
        select(PriceAlert).where(PriceAlert.account_id == ACC, PriceAlert.status == "new").order_by(PriceAlert.id)
    ):
        if a.nm_id in latest:  # возвращаем к самой первой цене, прежние оповещения закрываем
            latest[a.nm_id].status, latest[a.nm_id].note = "skipped", "позже было ещё одно изменение"
        latest[a.nm_id] = a
    for a in latest.values():
        done = s.scalar(
            select(func.count())
            .select_from(PriceAlert)
            .where(
                PriceAlert.nm_id == a.nm_id,
                PriceAlert.status == "reverted",
                PriceAlert.reverted_at > now - timedelta(days=1),
            )
        )
        c = _change(s, a)
        if a.nm_id in skip:
            a.status, a.note = "skipped", "артикул в списке «не возвращать»"
        elif c is None:
            a.status, a.note = "skipped", "цена уже прежняя"
        elif done >= MAX_REVERTS_PER_DAY:
            a.status, a.note = "skipped", f"уже возвращали {done} раза за сутки, WB снова понижает: верните вручную"
        else:
            todo.append((a, c))
            continue
        result["skipped"] += 1
    if todo:
        changes = [c for _, c in todo]
        res = pricing.send(s, client, changes, pricing.confirm_token(changes))
        for a, _ in todo:
            if res["status"] == "sent":
                a.status, a.reverted_at = "reverted", now
                result["reverted"] += 1
            else:
                a.status, a.note = "error", res["error"]
                result["error"] = res["error"]
    s.commit()
    return result


def alerts(s: Session, limit: int = 200) -> list[dict]:
    rows = s.scalars(select(PriceAlert).where(PriceAlert.account_id == ACC).order_by(PriceAlert.id.desc()).limit(limit))
    return [
        {
            "id": a.id,
            "nm_id": a.nm_id,
            "old_price": a.old_price,
            "old_discount_pct": a.old_discount_pct,
            "new_price": a.new_price,
            "new_discount_pct": a.new_discount_pct,
            "status": a.status,
            "note": a.note,
            "detected_at": a.detected_at,
            "reverted_at": a.reverted_at,
            "restored": restored(s, a),
        }
        for a in rows
    ]
