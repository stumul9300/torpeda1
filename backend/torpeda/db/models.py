"""Таблицы базы данных.

В каждой таблице с данными кабинета есть account_id: в v1.0 кабинет один (id=1),
в v2.0 добавятся другие без перестройки базы.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, func
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
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Price(Base):
    __tablename__ = "prices"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    nm_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    price: Mapped[Decimal] = mapped_column(Money)  # цена до скидки, из WB
    discount_pct: Mapped[Decimal] = mapped_column(Percent)  # скидка продавца, из WB
    club_discount_pct: Mapped[Decimal | None] = mapped_column(Percent)
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
    """Снимок остатков FBO по складам на момент последней загрузки."""

    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
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


class ReportRow(Base):
    """Строка детализации еженедельного финансового отчёта WB."""

    __tablename__ = "report_rows"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    rrd_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int | None] = mapped_column(Integer, index=True)
    nm_id: Mapped[int | None] = mapped_column(Integer, index=True)
    rr_dt: Mapped[date | None] = mapped_column(Date, index=True)
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
