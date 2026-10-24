"""Прочие отчёты (этап 5)."""

from datetime import datetime
from decimal import Decimal

from torpeda.db.models import FunnelRow, Order, PriceChange, Product

PERIOD = {"date_from": "2026-10-01", "date_to": "2026-10-31"}


def report(api, name, **params):
    resp = api.get(f"/api/reports/{name}", params=PERIOD | params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def order(srid, nm, basket, wh="Коледино", okrug="Центральный", region="Москва", cancel=False):
    return Order(account_id=1, srid=srid, nm_id=nm, date=datetime(2026, 10, 5), g_number=basket, warehouse=wh,
                 oblast=okrug, region=region, price_with_disc=Decimal(1000), is_cancel=cancel)  # fmt: skip


def test_coefficients(api, fake_wb):
    fake_wb.tariffs_coefs = False  # старый адрес тоже работает
    resp = api.post("/api/wb/sync-coefficients")
    assert resp.status_code == 200 and resp.json() == {"rows": 5}
    d = report(api, "coefficients", group="box")
    rows = {r["warehouse"]: r for r in d["rows"]}
    k = rows["Коледино"]
    assert k["d_2026-10-25"] == 0 and k["d_2026-10-26"] == 2 and k["d_2026-10-27"] is None
    assert (k["free_days"], k["open_days"]) == (1, 2)
    assert d["rows"][0]["warehouse"] == "Коледино"  # больше бесплатных дней — выше
    assert [r["warehouse"] for r in report(api, "coefficients", group="pallet")["rows"]] == ["Коледино"]


def test_geography_and_joint_sales(api, factory):
    with factory() as s:
        s.add_all([Product(account_id=1, nm_id=1, vendor_code="A"), Product(account_id=1, nm_id=2, vendor_code="B")])
        s.add_all(
            [
                order("o1", 1, "g1"),
                order("o2", 2, "g1"),
                order("o3", 1, "g2", wh="Казань", okrug="Приволжский", region="Татарстан"),
                order("o4", 2, "g2", wh="Казань", okrug="Приволжский", region="Татарстан"),
                order("o5", 1, "g3", okrug="Приволжский", region="Татарстан"),
                order("o6", 2, "g4", cancel=True),
            ]
        )
        s.commit()
    okr = {r["place"]: r for r in report(api, "geography", group="okrug")["rows"]}
    assert okr["Приволжский"]["orders"] == 3 and okr["Приволжский"]["share"] == 60
    wh = report(api, "geography", group="warehouse")["rows"]
    kol = {r["okrug"]: r for r in wh if r["warehouse"] == "Коледино"}
    assert kol["Центральный"]["share"] == 66.7

    js = report(api, "joint_sales")
    r = js["rows"][0]
    assert (r["nm_a"], r["nm_b"], r["baskets"], r["sa_a"]) == (1, 2, 2, "A")
    assert r["share_a"] == 66.7 and r["share_b"] == 100
    assert "2 из 3" in js["notes"][0]


def test_rides(api, fake_wb):
    api.post("/api/wb/sync-report", json=PERIOD)
    r = report(api, "rides")["rows"][0]
    # 30 поездок туда, 20 обратно, продано 10 − 1 возврат = 9; логистика 4347,82
    assert (r["deliveries"], r["back"], r["net"]) == (30, 20, 9)
    assert r["per_trip"] == 86.96 and r["wasted_trips"] == 41
    assert r["wasted_rub"] == 3565.21


def test_price_history(api, factory):
    with factory() as s:
        s.add(PriceChange(account_id=1, nm_id=1, old_price=Decimal(2000), old_discount_pct=Decimal(50),
                          new_price=Decimal(2200), new_discount_pct=Decimal(50), status="sent",
                          sent_at=datetime(2026, 10, 10, 12)))  # fmt: skip
        s.commit()
    r = report(api, "price_history")["rows"][0]
    assert r["old_final"] == 1000 and r["new_final"] == 1100 and r["change_pct"] == 10
    assert r["status"] == "отправлено"


def test_funnel_localization(api, factory):
    with factory() as s:
        s.add(FunnelRow(account_id=1, date_from=datetime(2026, 10, 1).date(), date_to=datetime(2026, 10, 31).date(),
                        nm_id=1, localization_pct=73, loaded_at=datetime(2026, 10, 24)))  # fmt: skip
        s.commit()
    assert report(api, "funnel")["rows"][0]["localization"] == 73
