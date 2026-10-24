"""Реклама (этап 4): статистика кампаний, списания, реклама в марже."""

from decimal import Decimal

from torpeda.db.models import Product

PERIOD = {"date_from": "2026-10-01", "date_to": "2026-10-20"}


def report(api, name, **params):
    resp = api.get(f"/api/reports/{name}", params=PERIOD | params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_sync_and_reports(api, factory, fake_wb):
    with factory() as s:
        s.add(Product(account_id=1, nm_id=418020031, vendor_code="8447", subject_name="Поло"))
        s.commit()
    resp = api.post("/api/wb/sync-ads", json=PERIOD)
    assert resp.status_code == 200, resp.text
    # 101 идёт, 102 завершена в периоде; 103 завершена давно, 104 в другом статусе — не берём
    assert resp.json() == {"campaigns": 2, "stats": 4, "costs": 2}
    ids = {r.url.params["ids"] for r in fake_wb.requests if r.url.path == "/adv/v3/fullstats"}
    assert ids == {"101,102"}

    rows = {r["nm_id"]: r for r in report(api, "ads", group="nm")["rows"]}
    r = rows[418020031]
    assert (r["views"], r["clicks"], r["orders"]) == (3000, 150, 6)
    assert r["spend"] == 701 and r["orders_sum"] == 18000
    assert r["ctr"] == 5 and r["cpc"] == 4.67 and r["drr"] == 3.89
    assert r["sa_name"] == "8447"

    camps = {r["advert_id"]: r for r in report(api, "ads", group="campaign")["rows"]}
    assert camps[101]["campaign"] == "Поло поиск" and camps[102]["type"] == "Автоматическая"
    assert report(api, "ads", group="day")["totals"]["spend"] == 800

    costs = report(api, "ad_costs")
    assert costs["totals"]["amount"] == 700
    assert {r["payment_type"] for r in costs["rows"]} == {"Баланс", "Счёт"}

    # повторная загрузка не задваивает
    api.post("/api/wb/sync-ads", json=PERIOD)
    assert report(api, "ads", group="day")["totals"]["spend"] == 800


def test_ads_reduce_margin(api, fake_wb):
    api.post("/api/wb/sync-report", json=PERIOD)
    before = {r["nm_id"]: r for r in report(api, "detail", group="nm")["rows"]}[418020031]
    api.post("/api/wb/sync-ads", json=PERIOD)
    d = report(api, "detail", group="nm")
    rows = {r["nm_id"]: r for r in d["rows"]}
    after = rows[418020031]
    assert after["advertising"] == 701
    assert Decimal(str(before["profit"])) - Decimal(str(after["profit"])) == 701
    # товар с рекламой, но без продаж, тоже виден: реклама — чистый минус
    assert rows[555]["profit"] == -99
    # по складам реклама не делится
    office = report(api, "detail", group="office")
    assert all(not r.get("advertising") for r in office["rows"])


def test_no_promotion_category(api, fake_wb):
    fake_wb.advert_enabled = False
    resp = api.post("/api/wb/sync-ads", json=PERIOD)
    assert resp.status_code == 502 and "«Продвижение»" in resp.json()["detail"]
