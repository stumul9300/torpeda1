"""Таблицы базы данных.

В каждой таблице с данными кабинета есть account_id: в v1.0 кабинет один (id=1),
в v2.0 добавятся другие без перестройки базы.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Money = Numeric(14, 2)
Percent = Numeric(7, 3)

DEFAULT_ACCOUNT_ID = 1


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))


class Product(Base):
    __tablename__ = "products"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    nm_id: Mapped[int] = mapped_column(Integer, primary_key=True)  # артикул WB
    vendor_code: Mapped[str | None] = mapped_column(String(100))  # артикул продавца
    title: Mapped[str | None] = mapped_column(String(500))
    brand: Mapped[str | None] = mapped_column(String(200))
    subject_id: Mapped[int | None] = mapped_column(Integer)
    subject_name: Mapped[str | None] = mapped_column(String(200))
    volume_l: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    photo_url: Mapped[str | None] = mapped_column(String(500))  # маленькое фото из карточки WB
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Price(Base):
    __tablename__ = "prices"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    nm_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    price: Mapped[Decimal] = mapped_column(Money)  # цена до скидки, из WB
    discount_pct: Mapped[Decimal] = mapped_column(Percent)  # скидка продавца, из WB
    club_discount_pct: Mapped[Decimal | None] = mapped_column(Percent)
    site_price: Mapped[Decimal | None] = mapped_column(Money)  # цена на сайте для покупателя в Москве
    site_price_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Расчётная цена: что пользователь ввёл в таблице. В WB не отправляется (репрайсера в v1 нет).
    calc_price: Mapped[Decimal | None] = mapped_column(Money)
    calc_discount_pct: Mapped[Decimal | None] = mapped_column(Percent)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class CostPrice(Base):
    """Себестоимость вводится вручную. История: новая запись на каждое изменение."""

    __tablename__ = "cost_prices"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    nm_id: Mapped[int] = mapped_column(Integer, index=True)
    cost: Mapped[Decimal] = mapped_column(Money)
    valid_from: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CommissionRate(Base):
    __tablename__ = "commission_rates"

    subject_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_name: Mapped[str | None] = mapped_column(String(200))
    fbo_pct: Mapped[Decimal] = mapped_column(Percent)
    fbs_pct: Mapped[Decimal] = mapped_column(Percent)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Stock(Base):
    """Снимок остатков по складам на момент последней загрузки: FBO — склады WB, FBS — склады продавца."""

    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    scheme: Mapped[str] = mapped_column(String(3), default="FBO")
    nm_id: Mapped[int] = mapped_column(Integer, index=True)
    warehouse: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(Integer)
    in_way_to_client: Mapped[int] = mapped_column(Integer, default=0)
    in_way_from_client: Mapped[int] = mapped_column(Integer, default=0)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime)


class Order(Base):
    __tablename__ = "orders"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    srid: Mapped[str] = mapped_column(String(100), primary_key=True)
    nm_id: Mapped[int] = mapped_column(Integer, index=True)
    date: Mapped[datetime] = mapped_column(DateTime, index=True)
    warehouse: Mapped[str | None] = mapped_column(String(200))
    price_with_disc: Mapped[Decimal | None] = mapped_column(Money)  # цена продавца
    finished_price: Mapped[Decimal | None] = mapped_column(Money)  # цена покупателя с СПП
    spp: Mapped[Decimal | None] = mapped_column(Percent)
    is_cancel: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_date: Mapped[datetime | None] = mapped_column(DateTime)
    supplier_article: Mapped[str | None] = mapped_column(String(100))
    tech_size: Mapped[str | None] = mapped_column(String(50))
    region: Mapped[str | None] = mapped_column(String(200))
    oblast: Mapped[str | None] = mapped_column(String(200))  # федеральный округ
    warehouse_type: Mapped[str | None] = mapped_column(String(100))
    total_price: Mapped[Decimal | None] = mapped_column(Money)  # цена без скидок
    discount_pct: Mapped[Decimal | None] = mapped_column(Percent)
    g_number: Mapped[str | None] = mapped_column(String(100))  # корзина покупателя


class Sale(Base):
    __tablename__ = "sales"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    sale_id: Mapped[str] = mapped_column(String(100), primary_key=True)  # S... продажа, R... возврат
    srid: Mapped[str | None] = mapped_column(String(100))
    nm_id: Mapped[int] = mapped_column(Integer, index=True)
    date: Mapped[datetime] = mapped_column(DateTime, index=True)
    warehouse: Mapped[str | None] = mapped_column(String(200))
    price_with_disc: Mapped[Decimal | None] = mapped_column(Money)
    finished_price: Mapped[Decimal | None] = mapped_column(Money)
    for_pay: Mapped[Decimal | None] = mapped_column(Money)
    spp: Mapped[Decimal | None] = mapped_column(Percent)
    supplier_article: Mapped[str | None] = mapped_column(String(100))
    tech_size: Mapped[str | None] = mapped_column(String(50))
    region: Mapped[str | None] = mapped_column(String(200))
    oblast: Mapped[str | None] = mapped_column(String(200))
    warehouse_type: Mapped[str | None] = mapped_column(String(100))
    g_number: Mapped[str | None] = mapped_column(String(100))


class Plan(Base):
    """План продаж на месяц: по товару (nm_id) или на весь кабинет (nm_id = 0)."""

    __tablename__ = "plans"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    month: Mapped[str] = mapped_column(String(7), primary_key=True)  # 2026-10
    nm_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    qty: Mapped[int | None] = mapped_column(Integer)
    revenue: Mapped[Decimal | None] = mapped_column(Money)


class ReportRow(Base):
    """Строка детализации еженедельного финансового отчёта WB."""

    __tablename__ = "report_rows"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    rrd_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int | None] = mapped_column(Integer, index=True)
    nm_id: Mapped[int | None] = mapped_column(Integer, index=True)
    rr_dt: Mapped[date | None] = mapped_column(Date, index=True)
    date_from: Mapped[date | None] = mapped_column(Date)  # период недельного отчёта
    date_to: Mapped[date | None] = mapped_column(Date)
    sa_name: Mapped[str | None] = mapped_column(String(100))  # артикул продавца
    ts_name: Mapped[str | None] = mapped_column(String(50))  # размер
    subject_name: Mapped[str | None] = mapped_column(String(200))
    brand_name: Mapped[str | None] = mapped_column(String(200))
    bonus_type_name: Mapped[str | None] = mapped_column(String(500))  # вид штрафа или удержания
    srid: Mapped[str | None] = mapped_column(String(100))
    doc_type_name: Mapped[str | None] = mapped_column(String(50))  # Продажа / Возврат
    supplier_oper_name: Mapped[str | None] = mapped_column(String(200))  # Продажа, Логистика, Хранение, Штраф...
    office_name: Mapped[str | None] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    retail_price_withdisc_rub: Mapped[Decimal] = mapped_column(Money, default=0)  # цена продавца
    retail_amount: Mapped[Decimal] = mapped_column(Money, default=0)  # сумма продажи с СПП
    ppvz_for_pay: Mapped[Decimal] = mapped_column(Money, default=0)  # к перечислению
    delivery_rub: Mapped[Decimal] = mapped_column(Money, default=0)  # логистика
    delivery_amount: Mapped[int] = mapped_column(Integer, default=0)  # доставок к клиенту
    return_amount: Mapped[int] = mapped_column(Integer, default=0)  # доставок обратно
    storage_fee: Mapped[Decimal] = mapped_column(Money, default=0)
    penalty: Mapped[Decimal] = mapped_column(Money, default=0)
    acceptance: Mapped[Decimal] = mapped_column(Money, default=0)
    deduction: Mapped[Decimal] = mapped_column(Money, default=0)  # прочие удержания
    acquiring_fee: Mapped[Decimal] = mapped_column(Money, default=0)
    additional_payment: Mapped[Decimal] = mapped_column(Money, default=0)
    rebill_logistic_cost: Mapped[Decimal] = mapped_column(Money, default=0)  # возмещение издержек по перевозке
    cashback_amount: Mapped[Decimal] = mapped_column(Money, default=0)  # баллы, удержанные по программе лояльности
    cashback_discount: Mapped[Decimal] = mapped_column(Money, default=0)  # компенсация скидки по программе лояльности
    cashback_commission_change: Mapped[Decimal] = mapped_column(Money, default=0)  # стоимость участия в программе
    raw: Mapped[str | None] = mapped_column(Text)  # строка WB целиком (JSON), для будущих отчётов


class SalesReport(Base):
    """Шапка еженедельного отчёта реализации из finance-api: итоги, с которыми сверяется детализация."""

    __tablename__ = "sales_reports"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    report_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date_from: Mapped[date | None] = mapped_column(Date)
    date_to: Mapped[date | None] = mapped_column(Date)
    create_date: Mapped[date | None] = mapped_column(Date)
    report_type: Mapped[int | None] = mapped_column(Integer)  # 1 — основной, 2 — по выкупам
    retail_amount: Mapped[Decimal] = mapped_column(Money, default=0)
    for_pay: Mapped[Decimal] = mapped_column(Money, default=0)
    delivery: Mapped[Decimal] = mapped_column(Money, default=0)
    storage: Mapped[Decimal] = mapped_column(Money, default=0)
    acceptance: Mapped[Decimal] = mapped_column(Money, default=0)
    deduction: Mapped[Decimal] = mapped_column(Money, default=0)
    penalty: Mapped[Decimal] = mapped_column(Money, default=0)
    additional_payment: Mapped[Decimal] = mapped_column(Money, default=0)
    cashback_amount: Mapped[Decimal] = mapped_column(Money, default=0)
    cashback_discount: Mapped[Decimal] = mapped_column(Money, default=0)
    cashback_commission_change: Mapped[Decimal] = mapped_column(Money, default=0)
    bank_payment: Mapped[Decimal] = mapped_column(Money, default=0)  # «Итого к оплате»


class Promotion(Base):
    __tablename__ = "promotions"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(500))
    type: Mapped[str | None] = mapped_column(String(50))  # regular / auto
    start_at: Mapped[datetime | None] = mapped_column(DateTime)
    end_at: Mapped[datetime | None] = mapped_column(DateTime)


class PromotionItem(Base):
    __tablename__ = "promotion_items"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    promotion_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nm_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    in_action: Mapped[bool] = mapped_column(Boolean)
    price: Mapped[Decimal | None] = mapped_column(Money)  # текущая цена до скидки
    discount_pct: Mapped[Decimal | None] = mapped_column(Percent)  # текущая скидка
    plan_price: Mapped[Decimal | None] = mapped_column(Money)  # цена до скидки для акции
    plan_discount_pct: Mapped[Decimal | None] = mapped_column(Percent)  # скидка для акции


class PriceChange(Base):
    """Журнал отправленных в WB цен. По нему можно вернуть прежнюю цену."""

    __tablename__ = "price_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    nm_id: Mapped[int] = mapped_column(Integer, index=True)
    old_price: Mapped[Decimal] = mapped_column(Money)
    old_discount_pct: Mapped[Decimal] = mapped_column(Percent)
    new_price: Mapped[Decimal] = mapped_column(Money)
    new_discount_pct: Mapped[Decimal] = mapped_column(Percent)
    wb_task_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))  # sent / error
    error: Mapped[str | None] = mapped_column(String(1000))
    sent_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FunnelRow(Base):
    """Воронка продаж по карточке за период (переходы → корзина → заказы → выкупы). WB считает сам за период."""

    __tablename__ = "funnel"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    date_from: Mapped[date] = mapped_column(Date, primary_key=True)
    date_to: Mapped[date] = mapped_column(Date, primary_key=True)
    nm_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    open_count: Mapped[int] = mapped_column(Integer, default=0)
    cart_count: Mapped[int] = mapped_column(Integer, default=0)
    wishlist: Mapped[int] = mapped_column(Integer, default=0)
    order_count: Mapped[int] = mapped_column(Integer, default=0)
    order_sum: Mapped[Decimal] = mapped_column(Money, default=0)
    buyout_count: Mapped[int] = mapped_column(Integer, default=0)
    buyout_sum: Mapped[Decimal] = mapped_column(Money, default=0)
    cancel_count: Mapped[int] = mapped_column(Integer, default=0)
    cancel_sum: Mapped[Decimal] = mapped_column(Money, default=0)
    localization_pct: Mapped[int | None] = mapped_column(Integer)  # заказы со склада в регионе покупателя
    loaded_at: Mapped[datetime] = mapped_column(DateTime)


class StorageRow(Base):
    """Платное хранение за день по размеру товара на складе."""

    __tablename__ = "paid_storage"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    date: Mapped[date] = mapped_column(Date, index=True)
    nm_id: Mapped[int] = mapped_column(Integer, index=True)
    warehouse: Mapped[str | None] = mapped_column(String(200))
    size: Mapped[str | None] = mapped_column(String(100))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))  # литры
    barcodes_count: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[Decimal] = mapped_column(Money, default=0)
    calc_type: Mapped[str | None] = mapped_column(String(200))


class AcceptanceRow(Base):
    """Платная приёмка: товар поставки, принятый в день."""

    __tablename__ = "paid_acceptance"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    date: Mapped[date] = mapped_column(Date, index=True)
    income_id: Mapped[int | None] = mapped_column(Integer)
    nm_id: Mapped[int] = mapped_column(Integer, index=True)
    subject: Mapped[str | None] = mapped_column(String(200))
    count: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[Decimal] = mapped_column(Money, default=0)


class AdStat(Base):
    """Статистика рекламной кампании за день по товару: показы, клики, затраты, заказы с рекламы."""

    __tablename__ = "ad_stats"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    advert_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    nm_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    views: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    atbs: Mapped[int] = mapped_column(Integer, default=0)  # в корзину
    orders: Mapped[int] = mapped_column(Integer, default=0)
    shks: Mapped[int] = mapped_column(Integer, default=0)  # заказано штук
    spend: Mapped[Decimal] = mapped_column(Money, default=0)
    orders_sum: Mapped[Decimal] = mapped_column(Money, default=0)


class AdCost(Base):
    """Списание за рекламу (история затрат WB): сколько и откуда списано по кампании."""

    __tablename__ = "ad_costs"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    at: Mapped[datetime] = mapped_column(DateTime, index=True)
    advert_id: Mapped[int] = mapped_column(Integer, index=True)
    campaign: Mapped[str | None] = mapped_column(String(300))
    advert_type: Mapped[int | None] = mapped_column(Integer)
    payment_type: Mapped[str | None] = mapped_column(String(100))
    doc_num: Mapped[int | None] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(Money, default=0)


class AcceptanceCoef(Base):
    """Коэффициенты приёмки на складах WB на ближайшие дни: −1 — приёмки нет, 0 — бесплатно, 2 — ×2 к тарифу."""

    __tablename__ = "acceptance_coefs"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    box_type_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    warehouse: Mapped[str | None] = mapped_column(String(200))
    box_type: Mapped[str | None] = mapped_column(String(100))
    coefficient: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    allow_unload: Mapped[bool] = mapped_column(Boolean, default=False)
    storage_coef: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))  # %
    delivery_coef: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))  # %
    loaded_at: Mapped[datetime] = mapped_column(DateTime)


class SyncLog(Base):
    """Итог последней загрузки каждого раздела: для вкладки «Настройки» → «Что пошло не так»."""

    __tablename__ = "sync_log"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    section: Mapped[str] = mapped_column(String(100), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime)
    ok: Mapped[bool] = mapped_column(Boolean)
    message: Mapped[str] = mapped_column(Text)


class Setting(Base):
    __tablename__ = "settings"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(500))


DEFAULT_SETTINGS = {
    "scheme": "FBO",  # схема, по которой считать комиссию в таблице
    "tax_pct": "7",  # налог от суммы продажи
    "acquiring_pct": "",  # пусто = брать фактический из отчётов
    "risk_margin_pct": "10",  # порог «зоны риска» по маржинальности
    "report_days": "30",  # за сколько дней брать фактическую логистику и хранение
}
