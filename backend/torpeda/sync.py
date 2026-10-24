"""Загрузка данных из API WB в базу.

Запуск из папки backend:
    uv run python -m torpeda.sync check      # проверить ключ и связь с WB
    uv run python -m torpeda.sync all        # загрузить всё за последние 30 дней
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from torpeda.config import get_settings
from torpeda.db import DEFAULT_ACCOUNT_ID, init_db, make_engine
from torpeda.db.models import (
    CommissionRate,
    Order,
    Price,
    Product,
    Promotion,
    PromotionItem,
    ReportRow,
    Sale,
    Stock,
)
from torpeda.wb_api.client import WBAuthError, WBClient, WBError

ACC = DEFAULT_ACCOUNT_ID


def _dec(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    return Decimal(str(v))


def _dt(v: str | None) -> datetime | None:
    if not v:
        return None
    return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)


def _d(v: str | None) -> date | None:
    dt = _dt(v)
    return dt.date() if dt else None


def sync_products(client: WBClient, s: Session) -> int:
    n = 0
    for c in client.iter_cards():
        dims = c.get("dimensions") or {}
        volume = None
        if dims.get("length") and dims.get("width") and dims.get("height"):
            volume = _dec(dims["length"]) * _dec(dims["width"]) * _dec(dims["height"]) / 1000  # см³ → литры
        s.merge(
            Product(
                account_id=ACC,
                nm_id=c["nmID"],
                vendor_code=c.get("vendorCode"),
                title=c.get("title"),
                brand=c.get("brand"),
                subject_id=c.get("subjectID"),
                subject_name=c.get("subjectName"),
                volume_l=volume,
            )
        )
        n += 1
    return n


def sync_prices(client: WBClient, s: Session) -> int:
    n = 0
    for g in client.iter_prices():
        sizes = g.get("sizes") or [{}]
        existing = s.get(Price, (ACC, g["nmID"]))
        price = Price(
            account_id=ACC,
            nm_id=g["nmID"],
            price=_dec(sizes[0].get("price")) or Decimal(0),
            discount_pct=_dec(g.get("discount")) or Decimal(0),
            club_discount_pct=_dec(g.get("clubDiscount")),
            # расчётную цену, введённую в таблице, не затираем
            calc_price=existing.calc_price if existing else None,
            calc_discount_pct=existing.calc_discount_pct if existing else None,
        )
        s.merge(price)
        n += 1
    return n


def sync_commissions(client: WBClient, s: Session) -> int:
    rows = client.get_commissions()
    for r in rows:
        s.merge(
            CommissionRate(
                subject_id=r["subjectID"],
                subject_name=r.get("subjectName"),
                fbo_pct=_dec(r.get("paidStorageKgvp")) or Decimal(0),
                fbs_pct=_dec(r.get("kgvpMarketplace")) or Decimal(0),
            )
        )
    return len(rows)


def sync_stocks(client: WBClient, s: Session, now: datetime, scheme: str) -> int:
    """Снимок остатков: FBO — склады WB, FBS — склады продавца. Старый снимок этой схемы заменяется."""
    rows = list(client.iter_stocks("wb" if scheme == "FBO" else "seller"))
    s.execute(delete(Stock).where(Stock.account_id == ACC, Stock.scheme == scheme))
    for r in rows:
        s.add(
            Stock(
                account_id=ACC,
                scheme=scheme,
                nm_id=r["nmId"],
                warehouse=r.get("warehouseName") or "",
                quantity=r.get("quantity") or 0,
                in_way_to_client=r.get("inWayToClient") or 0,
                in_way_from_client=r.get("inWayFromClient") or 0,
                snapshot_at=now,
            )
        )
    return len(rows)


def sync_orders(client: WBClient, s: Session, date_from: date) -> int:
    rows = client.get_orders(date_from)
    for r in rows:
        s.merge(
            Order(
                account_id=ACC,
                srid=r["srid"],
                nm_id=r["nmId"],
                date=_dt(r.get("date")),
                warehouse=r.get("warehouseName"),
                price_with_disc=_dec(r.get("priceWithDisc")),
                finished_price=_dec(r.get("finishedPrice")),
                spp=_dec(r.get("spp")),
                is_cancel=bool(r.get("isCancel")),
            )
        )
    return len(rows)


def sync_sales(client: WBClient, s: Session, date_from: date) -> int:
    rows = client.get_sales(date_from)
    for r in rows:
        s.merge(
            Sale(
                account_id=ACC,
                sale_id=r["saleID"],
                srid=r.get("srid"),
                nm_id=r["nmId"],
                date=_dt(r.get("date")),
                warehouse=r.get("warehouseName"),
                price_with_disc=_dec(r.get("priceWithDisc")),
                finished_price=_dec(r.get("finishedPrice")),
                for_pay=_dec(r.get("forPay")),
                spp=_dec(r.get("spp")),
            )
        )
    return len(rows)


REPORT_MONEY = (
    "retail_price_withdisc_rub",
    "retail_amount",
    "ppvz_for_pay",
    "delivery_rub",
    "storage_fee",
    "penalty",
    "acceptance",
    "deduction",
    "acquiring_fee",
    "additional_payment",
)


def sync_report(client: WBClient, s: Session, date_from: date, date_to: date) -> int:
    n = 0
    for r in client.iter_report_detail(date_from, date_to):
        s.merge(
            ReportRow(
                account_id=ACC,
                rrd_id=r["rrd_id"],
                report_id=r.get("realizationreport_id"),
                nm_id=r.get("nm_id") or None,
                rr_dt=_d(r.get("rr_dt")),
                doc_type_name=r.get("doc_type_name"),
                supplier_oper_name=r.get("supplier_oper_name"),
                office_name=r.get("office_name"),
                quantity=r.get("quantity") or 0,
                delivery_amount=r.get("delivery_amount") or 0,
                return_amount=r.get("return_amount") or 0,
                **{k: _dec(r.get(k)) or Decimal(0) for k in REPORT_MONEY},
            )
        )
        n += 1
    return n


def sync_promotions(client: WBClient, s: Session, now: datetime) -> tuple[int, int]:
    promos = client.get_promotions(now - timedelta(days=7), now + timedelta(days=60))
    items = 0
    for p in promos:
        s.merge(
            Promotion(
                account_id=ACC,
                id=p["id"],
                name=p.get("name") or "",
                type=p.get("type"),
                start_at=_dt(p.get("startDateTime")),
                end_at=_dt(p.get("endDateTime")),
            )
        )
        for it in client.iter_promotion_items(p["id"]):
            s.merge(
                PromotionItem(
                    account_id=ACC,
                    promotion_id=p["id"],
                    nm_id=it["id"],
                    in_action=bool(it.get("inAction")),
                    price=_dec(it.get("price")),
                    discount_pct=_dec(it.get("discount")),
                    plan_price=_dec(it.get("planPrice")),
                    plan_discount_pct=_dec(it.get("planDiscount")),
                )
            )
            items += 1
    return len(promos), items


# какую категорию включить у ключа, если WB отказал в доступе
KEY_CATEGORY = {
    "товары": "Контент",
    "цены": "Цены и скидки",
    "остатки FBO": "Аналитика",
    "остатки FBS": "Аналитика",
    "заказы": "Статистика",
    "продажи": "Статистика",
    "финотчёт": "Статистика",
    "акции": "Цены и скидки",
}


def sync_all(client: WBClient, factory: sessionmaker[Session], days: int = 30, now: datetime | None = None) -> dict:
    """Загружает всё по очереди. Ошибка одного раздела не мешает остальным."""
    now = now or datetime.now()
    date_from = (now - timedelta(days=days)).date()
    steps = {
        "товары": lambda s: sync_products(client, s),
        "цены": lambda s: sync_prices(client, s),
        "комиссии": lambda s: sync_commissions(client, s),
        "остатки FBO": lambda s: sync_stocks(client, s, now, "FBO"),
        "остатки FBS": lambda s: sync_stocks(client, s, now, "FBS"),
        "заказы": lambda s: sync_orders(client, s, date_from),
        "продажи": lambda s: sync_sales(client, s, date_from),
        "финотчёт": lambda s: sync_report(client, s, date_from, now.date()),
        "акции": lambda s: sync_promotions(client, s, now),
    }
    result: dict[str, Any] = {}
    for name, step in steps.items():
        with factory() as s:
            try:
                result[name] = step(s)
                s.commit()
            except WBAuthError as e:
                s.rollback()
                category = KEY_CATEGORY.get(name)
                hint = f"у ключа нет доступа, включите категорию «{category}». " if category else ""
                result[name] = f"ошибка: {hint}{e}"
            except WBError as e:
                s.rollback()
                result[name] = f"ошибка: {e}"
    return result


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "all"
    settings = get_settings()
    try:
        client = WBClient(settings.wb_api_token)
    except WBAuthError as e:
        print(e)
        return 1
    with client:
        if cmd == "check":
            ok = True
            for name, status in client.ping().items():
                print(f"{name}: {status}")
                ok = ok and status == "ok"
            return 0 if ok else 1
        factory = init_db(make_engine(settings.database_url))
        for name, res in sync_all(client, factory).items():
            print(f"{name}: {res}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
