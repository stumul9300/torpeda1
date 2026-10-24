"""Загрузка данных из API WB в базу.

Запуск из папки backend:
    uv run python -m torpeda.sync check      # проверить ключ и связь с WB
    uv run python -m torpeda.sync all        # загрузить всё за последние 30 дней
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from torpeda.config import get_settings
from torpeda.db import DEFAULT_ACCOUNT_ID, init_db, make_engine
from torpeda.db.models import (
    AcceptanceCoef,
    AcceptanceRow,
    AdCost,
    AdStat,
    CommissionRate,
    FunnelRow,
    Order,
    Price,
    Product,
    Promotion,
    PromotionItem,
    ReportRow,
    Sale,
    SalesReport,
    Stock,
    StorageRow,
    SyncLog,
)
from torpeda.wb_api.client import BASE_TOKEN_HINT, WBAuthError, WBClient, WBError, is_token_type_error

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


REMAINS_TO_CLIENT = "В пути до получателей"
REMAINS_FROM_CLIENT = "В пути возвраты на склад WB"


def _remains_rows(items: list[dict]) -> list[dict]:
    """Отчёт об остатках (warehouse_remains) в виде строк stocks-report: склад, количество, в пути."""
    rows = []
    for it in items:
        to_client = from_client = 0
        for w in it.get("warehouses") or []:
            name, qty = w.get("warehouseName") or "", w.get("quantity") or 0
            if name == REMAINS_TO_CLIENT:
                to_client += qty
            elif name == REMAINS_FROM_CLIENT:
                from_client += qty
            elif not name.startswith(("Всего", "В пути")):
                rows.append({"nmId": it["nmId"], "warehouseName": name, "quantity": qty})
        if to_client or from_client:
            rows.append({"nmId": it["nmId"], "warehouseName": "в пути", "quantity": 0,
                         "inWayToClient": to_client, "inWayFromClient": from_client})  # fmt: skip
    return rows


def sync_stocks(client: WBClient, s: Session, now: datetime, scheme: str) -> int:
    """Снимок остатков: FBO — склады WB, FBS — склады продавца. Старый снимок этой схемы заменяется.

    «Базовый» ключ WB к быстрому методу остатков не пускает: тогда FBO берём из отчёта об остатках."""
    try:
        rows = list(client.iter_stocks("wb" if scheme == "FBO" else "seller"))
    except WBAuthError as e:
        if not is_token_type_error(str(e)):
            raise
        if scheme == "FBS":
            raise WBAuthError(f"{BASE_TOKEN_HINT} Остатки FBO при этом загружаются запасным способом.") from e
        rows = _remains_rows(client.get_warehouse_remains())
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


def _place(r: dict) -> dict:
    """Общие поля заказа и продажи: размер, артикул продавца, куда и откуда."""
    return {
        "supplier_article": r.get("supplierArticle"),
        "tech_size": r.get("techSize"),
        "region": r.get("regionName"),
        "oblast": r.get("oblastOkrugName"),
        "warehouse_type": r.get("warehouseType"),
        "g_number": r.get("gNumber"),
    }


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
                cancel_date=_dt(r.get("cancelDate")) if bool(r.get("isCancel")) else None,
                total_price=_dec(r.get("totalPrice")),
                discount_pct=_dec(r.get("discountPercent")),
                **_place(r),
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
                **_place(r),
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
    "rebill_logistic_cost",
    "cashback_amount",
    "cashback_discount",
    "cashback_commission_change",
)

# шапка отчёта: поле finance-api → колонка SalesReport
SALES_REPORT_MONEY = {
    "retailAmountSum": "retail_amount",
    "forPaySum": "for_pay",
    "deliveryServiceSum": "delivery",
    "paidStorageSum": "storage",
    "paidAcceptanceSum": "acceptance",
    "deductionSum": "deduction",
    "penaltySum": "penalty",
    "additionalPaymentSum": "additional_payment",
    "cashbackAmountSum": "cashback_amount",
    "cashbackDiscountSum": "cashback_discount",
    "cashbackCommissionChangeSum": "cashback_commission_change",
    "bankPaymentSum": "bank_payment",
}


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
                date_from=_d(r.get("date_from")),
                date_to=_d(r.get("date_to")),
                sa_name=r.get("sa_name"),
                ts_name=r.get("ts_name"),
                subject_name=r.get("subject_name"),
                brand_name=r.get("brand_name"),
                bonus_type_name=r.get("bonus_type_name"),
                srid=r.get("srid"),
                raw=json.dumps(r, ensure_ascii=False),
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
    sync_sales_reports(client, s, date_from, date_to)
    return n


def sync_sales_reports(client: WBClient, s: Session, date_from: date, date_to: date) -> int:
    """Шапки отчётов для сверки. Если у ключа нет категории «Финансы», детализация всё равно загрузится."""
    try:
        reports = client.get_sales_reports(date_from, date_to)
    except WBError:
        return 0
    for r in reports:
        s.merge(
            SalesReport(
                account_id=ACC,
                report_id=r["reportId"],
                date_from=_d(r.get("dateFrom")),
                date_to=_d(r.get("dateTo")),
                create_date=_d(r.get("createDate")),
                report_type=r.get("reportType"),
                **{col: _dec(r.get(key)) or Decimal(0) for key, col in SALES_REPORT_MONEY.items()},
            )
        )
    return len(reports)


def sync_funnel(client: WBClient, s: Session, date_from: date, date_to: date, now: datetime | None = None) -> int:
    """Воронка за ровно этот период: прежние данные за тот же период заменяются."""
    now = now or datetime.now()
    rows = list(client.iter_funnel(date_from, date_to))
    s.execute(
        delete(FunnelRow).where(
            FunnelRow.account_id == ACC, FunnelRow.date_from == date_from, FunnelRow.date_to == date_to
        )
    )
    for r in rows:
        nm = (r.get("product") or {}).get("nmId")
        st = ((r.get("statistic") or {}).get("selected")) or {}
        if not nm:
            continue
        s.add(
            FunnelRow(
                account_id=ACC,
                date_from=date_from,
                date_to=date_to,
                nm_id=nm,
                open_count=st.get("openCount") or 0,
                cart_count=st.get("cartCount") or 0,
                wishlist=st.get("addToWishlist") or 0,
                order_count=st.get("orderCount") or 0,
                order_sum=_dec(st.get("orderSum")) or 0,
                buyout_count=st.get("buyoutCount") or 0,
                buyout_sum=_dec(st.get("buyoutSum")) or 0,
                cancel_count=st.get("cancelCount") or 0,
                cancel_sum=_dec(st.get("cancelSum")) or 0,
                localization_pct=st.get("localizationPercent"),
                loaded_at=now,
            )
        )
    return len(rows)


def sync_paid_storage(client: WBClient, s: Session, date_from: date, date_to: date) -> int:
    n = 0
    for start, end, rows in client.iter_paid_storage(date_from, date_to):
        s.execute(
            delete(StorageRow).where(StorageRow.account_id == ACC, StorageRow.date >= start, StorageRow.date <= end)
        )
        for r in rows:
            s.add(
                StorageRow(
                    account_id=ACC,
                    date=_d(r.get("date")) or start,
                    nm_id=r.get("nmId") or 0,
                    warehouse=r.get("warehouse"),
                    size=r.get("size"),
                    volume=_dec(r.get("volume")),
                    barcodes_count=r.get("barcodesCount") or 0,
                    price=_dec(r.get("warehousePrice")) or 0,
                    calc_type=r.get("calcType"),
                )
            )
        n += len(rows)
        s.commit()  # каждая порция по 8 дней сохраняется сразу: загрузка за месяц идёт несколько минут
    return n


def sync_acceptance(client: WBClient, s: Session, date_from: date, date_to: date) -> int:
    n = 0
    for start, end, rows in client.iter_acceptance(date_from, date_to):
        s.execute(
            delete(AcceptanceRow).where(
                AcceptanceRow.account_id == ACC, AcceptanceRow.date >= start, AcceptanceRow.date <= end
            )
        )
        for r in rows:
            s.add(
                AcceptanceRow(
                    account_id=ACC,
                    date=_d(r.get("shkCreateDate")) or start,
                    income_id=r.get("incomeId"),
                    nm_id=r.get("nmID") or r.get("nmId") or 0,
                    subject=r.get("subjectName"),
                    count=r.get("count") or 0,
                    total=_dec(r.get("total")) or 0,
                )
            )
        n += len(rows)
        s.commit()
    return n


def sync_acceptance_coefs(client: WBClient, s: Session, now: datetime | None = None) -> int:
    """Коэффициенты приёмки: снимок на ближайшие дни, прежний заменяется."""
    now = now or datetime.now()
    rows = client.get_acceptance_coefficients()
    s.execute(delete(AcceptanceCoef).where(AcceptanceCoef.account_id == ACC))
    seen = set()
    for r in rows:
        key = (_d(r.get("date")), r.get("warehouseID") or 0, r.get("boxTypeID") or 0)
        if key in seen or key[0] is None:
            continue
        seen.add(key)
        s.add(
            AcceptanceCoef(
                account_id=ACC,
                date=key[0],
                warehouse_id=key[1],
                box_type_id=key[2],
                warehouse=r.get("warehouseName"),
                box_type=r.get("boxTypeName"),
                coefficient=_dec(r.get("coefficient")),
                allow_unload=bool(r.get("allowUnload")),
                storage_coef=_dec(r.get("storageCoef")),
                delivery_coef=_dec(r.get("deliveryCoef")),
                loaded_at=now,
            )
        )
    return len(seen)


def sync_ads(client: WBClient, s: Session, date_from: date, date_to: date) -> dict:
    """Реклама за даты: статистика по товарам и дням и списания. Прежние данные за эти дни заменяются."""
    ids = client.get_advert_ids(date_from)
    stats: dict[tuple, dict] = {}
    for camp in client.iter_ad_fullstats(ids, date_from, date_to) if ids else []:
        for day in camp.get("days") or []:
            d = _d(day.get("date"))
            for app_ in day.get("apps") or []:
                for nm in app_.get("nms") or []:
                    key = (camp["advertId"], d, nm.get("nmId") or 0)
                    a = stats.setdefault(key, {"views": 0, "clicks": 0, "atbs": 0, "orders": 0, "shks": 0,
                                               "spend": Decimal(0), "orders_sum": Decimal(0)})  # fmt: skip
                    for f in ("views", "clicks", "atbs", "orders", "shks"):
                        a[f] += nm.get(f) or 0
                    a["spend"] += _dec(nm.get("sum")) or 0
                    a["orders_sum"] += _dec(nm.get("sum_price")) or 0
    costs = list(client.iter_ad_costs(date_from, date_to))

    s.execute(delete(AdStat).where(AdStat.account_id == ACC, AdStat.date >= date_from, AdStat.date <= date_to))
    for (advert_id, d, nm_id), a in stats.items():
        s.add(AdStat(account_id=ACC, advert_id=advert_id, date=d, nm_id=nm_id, **a))
    s.execute(
        delete(AdCost).where(
            AdCost.account_id == ACC,
            AdCost.at >= datetime.combine(date_from, datetime.min.time()),
            AdCost.at < datetime.combine(date_to + timedelta(days=1), datetime.min.time()),
        )
    )
    for c in costs:
        s.add(
            AdCost(
                account_id=ACC,
                at=_dt(c.get("updTime")) or datetime.combine(date_from, datetime.min.time()),
                advert_id=c.get("advertId") or 0,
                campaign=c.get("campName"),
                advert_type=c.get("advertType"),
                payment_type=c.get("paymentType"),
                doc_num=c.get("updNum"),
                amount=_dec(c.get("updSum")) or 0,
            )
        )
    return {"campaigns": len(ids), "stats": len(stats), "costs": len(costs)}


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
    "финотчёт": "Финансы",
    "акции": "Цены и скидки",
}


SYNC_UNITS = {"товары": "карточек", "цены": "товаров", "комиссии": "предметов", "остатки FBO": "строк",
              "остатки FBS": "строк", "заказы": "заказов", "продажи": "строк", "финотчёт": "строк"}  # fmt: skip


def describe(name: str, result: Any) -> str:
    """Итог раздела для человека: «остатки FBO: получено 1 234 строк» или текст ошибки."""
    if isinstance(result, str):
        return f"{name}: {result}"
    if isinstance(result, tuple):  # акции: (акций, товаров в акциях)
        return f"{name}: получено акций {result[0]}, товаров в них {result[1]}"
    text = f"{name}: получено {result:,} {SYNC_UNITS.get(name, 'строк')}".replace(",", " ")
    if result == 0 and name.startswith("остатки"):
        text += " — WB ответил пустым списком (если товары на складе есть, нажмите «Проверить остатки» в «Настройках»)"
    return text


def sync_all(
    client: WBClient,
    factory: sessionmaker[Session],
    days: int = 30,
    now: datetime | None = None,
    on_step: Callable[[str, int, int, str | None], None] | None = None,
) -> dict:
    """Загружает всё по очереди. Ошибка одного раздела не мешает остальным.

    on_step(раздел, номер, всего, итог) вызывается перед разделом (итог None) и после него.
    В журнал пишется время окончания каждого раздела, если now не задан явно."""
    log_at = now
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
    for i, (name, step) in enumerate(steps.items(), start=1):
        if on_step:
            on_step(name, i, len(steps), None)
        with factory() as s:
            try:
                result[name] = step(s)
                log_sync(s, name, True, f"загружено: {result[name]}", log_at)
                s.commit()
            except WBAuthError as e:
                s.rollback()
                category = KEY_CATEGORY.get(name)
                if is_token_type_error(str(e)) or BASE_TOKEN_HINT in str(e):
                    hint = "" if BASE_TOKEN_HINT in str(e) else BASE_TOKEN_HINT + " "
                else:
                    hint = f"у ключа нет доступа, включите категорию «{category}». " if category else ""
                result[name] = f"ошибка: {hint}{e}"
            except WBError as e:
                s.rollback()
                result[name] = f"ошибка: {e}"
            except Exception as e:  # неожиданный ответ WB или сбой сети не должен ронять всю загрузку
                s.rollback()
                result[name] = f"ошибка: {type(e).__name__}: {e}"
            if str(result[name]).startswith("ошибка"):
                with factory() as s2:
                    log_sync(s2, name, False, str(result[name]), log_at)
                    s2.commit()
        if on_step:
            on_step(name, i, len(steps), describe(name, result[name]))
    return result


def log_sync(s: Session, section: str, ok: bool, message: str, now: datetime | None = None) -> None:
    s.merge(SyncLog(account_id=ACC, section=section, at=now or datetime.now(), ok=ok, message=message[:2000]))


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
