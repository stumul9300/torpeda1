"""Остатки в штуках и деньгах (этап 3)."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from torpeda.db.models import CostPrice, Order, Price, Product, Stock

PERIOD = {"date_from": "2026-10-01", "date_to": "2026-10-10"}
NOW = datetime(2026, 10, 20, 9)


def st(nm, wh, qty, scheme="FBO", to_client=0):
    return Stock(account_id=1, scheme=scheme, nm_id=nm, warehouse=wh, quantity=qty, in_way_to_client=to_client,
                 in_way_from_client=0, snapshot_at=NOW)  # fmt: skip


@pytest.fixture
def data(api, factory):
    with factory() as s:
        s.add_all(
            [
                Product(account_id=1, nm_id=1, vendor_code="A-1", title="Платье", subject_name="Платья"),
                Product(account_id=1, nm_id=2, vendor_code="B-2", title="Юбка", subject_name="Юбки"),
                Price(account_id=1, nm_id=1, price=Decimal(2000), discount_pct=Decimal(50)),
                Price(account_id=1, nm_id=2, price=Decimal(1000), discount_pct=Decimal(0)),
                CostPrice(account_id=1, nm_id=1, cost=Decimal(300), valid_from=date(2026, 1, 1)),
                st(1, "Коледино", 10, to_client=2),
                st(1, "Коледино", 5),  # другой размер на том же складе
                st(1, "Мой склад", 4, scheme="FBS"),
                st(2, "Тула", 3),
            ]
        )
        for i in range(5):
            s.add(Order(account_id=1, srid=f"o{i}", nm_id=1, date=datetime(2026, 10, 1 + i), is_cancel=i == 4))
        s.commit()
    return api


def report(api, group):
    resp = api.get("/api/reports/stocks", params=PERIOD | {"group": group})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_by_nm(data):
    d = report(data, "nm")
    rows = {r["nm_id"]: r for r in d["rows"]}
    r = rows[1]
    assert (r["fbo"], r["fbs"], r["total"], r["to_client"]) == (15, 4, 19, 2)
    assert r["cost_sum"] == 19 * 300 and r["price_sum"] == 19 * 1000
    assert r["orders_per_day"] == 0.4 and r["days_left"] == 47
    assert rows[2]["cost_sum"] == 0 and rows[2]["days_left"] is None
    assert d["totals"]["total"] == 22 and d["totals"]["price_sum"] == 22000
    assert any("Без себестоимости 3 шт" in n for n in d["notes"])


def test_by_warehouse(data):
    rows = {(r["scheme"], r["warehouse"]): r for r in report(data, "warehouse")["rows"]}
    assert rows[("FBO", "Коледино")]["fbo"] == 15
    assert rows[("FBS", "Мой склад")]["fbs"] == 4
    assert rows[("FBO", "Тула")]["nm_count"] == 1


def test_by_nm_warehouse_and_excel(data):
    rows = report(data, "nm_warehouse")["rows"]
    assert len(rows) == 3
    resp = data.get("/api/reports/stocks.xlsx", params=PERIOD | {"group": "nm"})
    assert resp.status_code == 200 and resp.content[:2] == b"PK"


def test_empty(api):
    d = report(api, "nm")
    assert d["rows"] == [] and "Остатков нет" in d["notes"][0]
