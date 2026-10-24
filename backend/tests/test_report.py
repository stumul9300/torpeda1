"""Эталоны — отчёт «Ракеты» по финансовым отчётам WB (выгрузка от 23.10.2026).

Взяты три строки: итог по складу, артикул с удержанием баллов лояльности
и артикул с рекламой. Полная сверка шла по всем 9 892 строкам файла.
"""

from decimal import Decimal

from torpeda.calc.report import ReportTotals, calculate_report

D = Decimal


def q(v):
    return v.quantize(D("0.01"))


def test_warehouse_total():
    r = calculate_report(
        ReportTotals(
            net_qty=14151,
            supplier_sales=D("31462753.02"),
            payout_sales=D("21477587.97"),
            logistics=D("4739605.01"),
            storage=D("128094.03"),
            acceptance=D("495"),
            penalties=D("20195.7"),
            loyalty_compensation=D("1290.36"),
            cost=D("7889187"),
        )
    )
    assert q(r.profit) == D("8701301.59")
    assert q(r.roi_pct) == D("110.29")
    assert q(r.margin_pct) == D("27.66")
    assert q(r.profit_per_unit) == D("614.89")
    assert q(r.logistics_per_unit) == D("334.93")
    assert q(r.storage_per_unit) == D("9.05")


def test_article_with_loyalty_points():
    r = calculate_report(
        ReportTotals(
            net_qty=28,
            supplier_sales=D("75546.12"),
            payout_sales=D("46054.13"),
            logistics=D("10426.94"),
            storage=D("46.76"),
            loyalty_points=D("452"),
            cost=D("19600"),
        )
    )
    assert q(r.profit) == D("15528.43")
    assert q(r.roi_pct) == D("79.23")
    assert q(r.margin_pct) == D("20.55")
    assert q(r.profit_per_unit) == D("554.59")


def test_article_with_advertising_is_loss():
    r = calculate_report(
        ReportTotals(
            net_qty=12,
            supplier_sales=D("45835"),
            payout_sales=D("26377.99"),
            logistics=D("12882.25"),
            storage=D("2338.93"),
            penalties=D("500"),
            advertising=D("129000"),  # нормированные рекламные затраты
            cost=D("8400"),
        )
    )
    assert q(r.profit) == D("-126743.19")
    assert q(r.roi_pct) == D("-1508.85")
    assert q(r.profit_per_unit) == D("-10561.93")
