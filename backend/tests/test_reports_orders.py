"""Заказы и продажи (этап 2): выкуп по srid, время доставки, СПП, ABC, план-факт."""

from datetime import datetime
from decimal import Decimal

import pytest

from torpeda.db.models import Order, Product, Sale

PERIOD = {"date_from": "2026-10-01", "date_to": "2026-10-31"}


def o(srid, nm, day, price, spp, cancel=False, wh="Коледино", region="Москва"):
    return Order(account_id=1, srid=srid, nm_id=nm, date=datetime(2026, 10, day, 10), price_with_disc=Decimal(price),
                 finished_price=Decimal(price) * (100 - spp) / 100, spp=Decimal(spp), is_cancel=cancel,
                 warehouse=wh, region=region, tech_size="S")  # fmt: skip


def sale(sid, srid, nm, day, price, for_pay):
    return Sale(account_id=1, sale_id=sid, srid=srid, nm_id=nm, date=datetime(2026, 10, day, 10),
                price_with_disc=Decimal(price), for_pay=Decimal(for_pay), warehouse="Коледино")  # fmt: skip


@pytest.fixture
def data(api, factory):
    with factory() as s:
        s.add_all([Product(account_id=1, nm_id=1, vendor_code="A-1", title="Платье", subject_name="Платья"),
                   Product(account_id=1, nm_id=2, vendor_code="B-2", title="Юбка", subject_name="Юбки")])  # fmt: skip
        s.add_all(
            [
                o("o1", 1, 1, 1000, 20),
                o("o2", 1, 2, 1000, 30),
                o("o3", 1, 3, 1000, 25, cancel=True),
                o("o4", 2, 5, 500, 25, wh="Тула", region="Тула"),
                o("o5", 2, 5, 500, 25, wh="Тула", region="Тула"),
                sale("S1", "o1", 1, 4, 1000, 700),
                sale("S2", "o2", 1, 3, 1000, 700),
                sale("R2", "o2", 1, 10, -1000, -700),
                sale("S5", "o5", 2, 6, 500, 350),
            ]
        )
        s.commit()
    return api


def report(api, name, **params):
    resp = api.get(f"/api/reports/{name}", params=PERIOD | params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def by_nm(data):
    return {r["nm_id"]: r for r in data["rows"]}


def test_orders_sales(data):
    rows = by_nm(report(data, "orders_sales", group="nm"))
    r = rows[1]
    assert (r["orders"], r["cancels"], r["sales"], r["returns"], r["net"]) == (3, 1, 2, 1, 1)
    assert r["net_sum"] == 1000 and r["for_pay"] == 700
    assert r["buyout_pct"] == 50  # 1 / (3 − 1)
    assert r["sa_name"] == "A-1"
    assert r["spp"] == 25
    days = report(data, "orders_sales", group="day")
    assert days["rows"][0]["day"] == "2026-10-10"  # новые дни сверху
    assert report(data, "orders_sales", group="region")["columns"][0]["header"] == "Регион"


def test_buyout_by_srid(data):
    rows = by_nm(report(data, "buyout"))
    assert (rows[1]["sold"], rows[1]["returned"], rows[1]["cancelled"]) == (1, 1, 1)
    assert rows[1]["buyout_pct"] == pytest.approx(33.33, abs=0.01)
    assert rows[2]["in_transit"] == 1 and rows[2]["buyout_pct"] == 100


def test_delivery_time(data):
    rows = by_nm(report(data, "delivery_time"))
    assert rows[1]["avg_days"] == 2  # 3 и 1 день
    assert rows[2]["median_days"] == 1
    wh = report(data, "delivery_time", group="warehouse")
    assert {r["warehouse"] for r in wh["rows"]} == {"Коледино", "Тула"}


def test_spp(data):
    d = report(data, "spp")
    assert d["totals"]["spp_min"] == 20 and d["totals"]["spp_max"] == 30


def test_abc(data):
    rows = by_nm(report(data, "abc"))
    assert rows[1]["abc_revenue"] == "A"
    assert rows[1]["revenue"] == 1000  # 1000 + 1000 − 1000
    assert "m_2026-10" in rows[1]


def test_plan_fact(data):
    plan = {"month": "2026-10", "nm_id": 0, "qty": 10, "revenue": "5000"}
    assert data.put("/api/plans", json=plan).status_code == 200
    assert data.put("/api/plans", json={"month": "2026-13x"}).status_code == 422
    rows = report(data, "plan_fact")["rows"]
    total = next(r for r in rows if r["nm_id"] == "Весь кабинет")
    assert (total["plan_qty"], total["fact_qty"]) == (10, 2)  # 3 продажи − 1 возврат
    assert total["qty_pct"] == 20
    assert total["revenue_pct"] == 30  # 1500 / 5000


def test_sync_orders(api, fake_wb):
    assert api.post("/api/wb/sync-orders", json={"date_from": "2026-08-01", "date_to": "2026-10-24"}).json() == {
        "orders": 1,
        "sales": 1,
    }
    req = [r for r in fake_wb.requests if r.url.path == "/api/v1/supplier/orders"][-1]
    assert req.url.params["dateFrom"] == "2026-08-01"
