"""Воронка продаж, платное хранение и приёмка (этап 4)."""

from torpeda.db.models import Product

PERIOD = {"date_from": "2026-10-01", "date_to": "2026-10-20"}


def report(api, name, **params):
    resp = api.get(f"/api/reports/{name}", params=PERIOD | params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_funnel(api, factory, fake_wb):
    with factory() as s:
        s.add(Product(account_id=1, nm_id=418020031, vendor_code="8447", subject_name="Поло"))
        s.commit()
    assert "Воронки за эти даты нет" in report(api, "funnel")["notes"][0]
    resp = api.post("/api/wb/sync-funnel", json=PERIOD)
    assert resp.status_code == 200 and resp.json() == {"rows": 1}
    d = report(api, "funnel")
    r = d["rows"][0]
    assert r["sa_name"] == "8447" and r["open_count"] == 1000
    assert (r["cart_pct"], r["order_pct"], r["buyout_pct"]) == (10, 40, 75)
    assert d["totals"]["order_sum"] == 80000
    # повторная загрузка за те же даты не задваивает
    api.post("/api/wb/sync-funnel", json=PERIOD)
    assert len(report(api, "funnel")["rows"]) == 1
    # за другие даты воронки нет
    other = api.get("/api/reports/funnel", params={"date_from": "2026-10-01", "date_to": "2026-10-10"}).json()
    assert other["rows"] == []


def test_storage_and_acceptance(api, fake_wb):
    resp = api.post("/api/wb/sync-services", json=PERIOD)
    assert resp.status_code == 200, resp.text
    # хранение — по 8 дней: 1–8, 9–16, 17–20; приёмка — одним отчётом
    assert resp.json() == {"storage": 3, "acceptance": 1}
    storage_tasks = [r for r in fake_wb.requests if r.url.path == "/api/v1/paid_storage"]
    assert [r.url.params["dateTo"] for r in storage_tasks] == ["2026-10-08", "2026-10-16", "2026-10-20"]

    d = report(api, "storage", group="nm")
    r = d["rows"][0]
    assert r["price"] == 22.95 and r["units"] == 3 and r["per_unit"] == 2.55
    assert d["totals"]["price"] == 22.95
    by_day = report(api, "storage", group="day")["rows"]
    assert [x["day"] for x in by_day] == ["2026-10-01", "2026-10-09", "2026-10-17"]
    assert report(api, "storage", group="warehouse")["rows"][0]["warehouse"] == "Коледино"

    a = report(api, "acceptance", group="nm")
    assert a["rows"][0]["total"] == 873.04 and a["rows"][0]["per_unit"] == 21.83
    inc = report(api, "acceptance", group="income")["rows"][0]
    assert inc["income_id"] == 11834106 and inc["date"] == "2026-10-01"

    # повторная загрузка заменяет данные за те же дни
    api.post("/api/wb/sync-services", json=PERIOD)
    assert report(api, "storage", group="nm")["rows"][0]["price"] == 22.95


def test_no_analytics_category(api, fake_wb):
    fake_wb.analytics_enabled = False
    resp = api.post("/api/wb/sync-funnel", json=PERIOD)
    assert resp.status_code == 502 and "«Аналитика»" in resp.json()["detail"]
    log = api.get("/api/sync-log").json()
    assert any(x["section"] == "воронка" and not x["ok"] for x in log)
