"""Эталоны — калькулятор «Ракеты», товар 418020031 (скриншот от 23.10.2026).

Общие параметры: предмет «Поло», FBO 43,5%, эквайринг 2,41%, себестоимость 700,
выкуп 34%, логистика туда 118,645 / обратно 69,1, реклама 31,69, хранение 0,004 × 30 дней.
Налог в «Ракете» был выключен.
"""

from decimal import Decimal

import pytest

from torpeda.calc import CommissionRates, Scheme, UnitInput, calculate, logistics, price_for_target_margin
from torpeda.calc.unit_economics import price_before_discount_for, seller_price

D = Decimal


def raketa_input(price_before_discount: str, discount: str, tax: str = "0") -> UnitInput:
    rates = CommissionRates(fbo_pct=D("43.5"), fbs_pct=D("48"))
    return UnitInput(
        price_before_discount=D(price_before_discount),
        discount_pct=D(discount),
        cost=D("700"),
        commission_pct=rates.for_scheme(Scheme.FBO),
        logistics_per_unit=logistics.per_sold_unit(D("118.645"), D("69.1"), D("34")),
        acquiring_pct=D("2.41"),
        tax_pct=D(tax),
        advertising_per_unit=D("31.69"),
        storage_per_unit=logistics.storage_per_unit(D("0.004"), D("30")),
        spp_pct=D("29"),
    )


def test_raketa_current_price():
    r = calculate(raketa_input("5123", "40")).rounded()
    assert r.seller_price == D("3073.80")
    assert r.price_with_spp == D("2182")
    assert r.commission == D("1337.10")
    assert r.logistics == D("483.09")
    assert r.acquiring == D("74.08")
    assert r.storage == D("0.12")
    assert r.profit == D("447.72")
    assert r.roi_pct == D("63.96")
    assert r.margin_pct == D("14.57")


def test_raketa_new_price():
    r = calculate(raketa_input("5109", "39")).rounded()
    assert r.seller_price == D("3116.49")
    assert r.price_with_spp == D("2213")
    assert r.commission == D("1355.67")
    assert r.acquiring == D("75.11")
    assert r.profit == D("470.81")
    assert r.roi_pct == D("67.26")
    assert r.margin_pct == D("15.11")


def test_tax_7_pct_from_sale_amount():
    r = calculate(raketa_input("5123", "40", tax="7")).rounded()
    assert r.tax == D("215.17")  # 3073,80 × 7%
    assert r.profit == D("232.55")  # 447,72 − 215,17


def test_fbs_uses_its_own_commission():
    rates = CommissionRates(fbo_pct=D("43.5"), fbs_pct=D("48"))
    assert rates.for_scheme(Scheme.FBS) == D("48")


def test_loss_detection():
    r = calculate(raketa_input("2000", "40"))
    assert r.is_loss
    assert r.profit < 0


def test_zero_cost_and_zero_price_do_not_crash():
    base = raketa_input("0", "0")
    r = calculate(UnitInput(**{**base.__dict__, "cost": D("0")}))
    assert r.roi_pct is None
    assert r.margin_pct is None


def test_price_for_target_margin_round_trip():
    inp = raketa_input("5123", "40", tax="7")
    p = price_for_target_margin(inp, D("20"))
    p0 = price_before_discount_for(p, inp.discount_pct)
    r = calculate(UnitInput(**{**inp.__dict__, "price_before_discount": p0}))
    assert r.seller_price == pytest.approx(p)
    assert r.margin_pct.quantize(D("0.0001")) == D("20.0000")


def test_price_for_impossible_margin_is_none():
    assert price_for_target_margin(raketa_input("5123", "40"), D("60")) is None


def test_seller_price():
    assert seller_price(D("5123"), D("40")) == D("3073.80")
