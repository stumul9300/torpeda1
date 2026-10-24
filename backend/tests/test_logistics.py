from decimal import Decimal

from torpeda.calc import logistics

D = Decimal


def test_per_sold_unit_matches_raketa():
    # 118,645 / 0,34 + 69,1 × 0,66 / 0,34 = 483,09
    assert logistics.per_sold_unit(D("118.645"), D("69.1"), D("34")).quantize(D("0.01")) == D("483.09")


def test_per_sold_unit_full_buyout_is_forward_only():
    assert logistics.per_sold_unit(D("100"), D("50"), D("100")) == D("100")


def test_per_sold_unit_zero_buyout():
    assert logistics.per_sold_unit(D("100"), D("50"), D("0")) is None


def test_from_report():
    # склад Коледино: 4 739 605,01 руб / 14 151 шт = 334,93
    assert logistics.from_report(D("4739605.01"), 14151).quantize(D("0.01")) == D("334.93")
    assert logistics.from_report(D("100"), 0) is None


def test_tariff_forward():
    assert logistics.tariff_forward(D("2.65"), D("46"), D("14"), D("1.5")) == D("103.65")
    assert logistics.tariff_forward(D("0.5"), D("46"), D("14")) == D("46")


def test_storage():
    assert logistics.storage_per_unit(D("0.004"), D("30")) == D("0.120")
