"""Таблица товаров, себестоимость, акции и отправка цен — через HTTP API, с поддельным WB."""

from datetime import date
from decimal import Decimal

import pytest

from torpeda.db.models import Price, PriceChange, ReportRow


@pytest.fixture
def synced(api, factory):
    assert api.post("/api/wb/sync").status_code == 200
    # даты отчёта сдвигаем к сегодняшнему дню, чтобы попасть в окно 30 дней
    with factory() as s:
        for r in s.query(ReportRow):
            r.rr_dt = date.today()
        s.commit()
    api.put("/api/settings", json={"tax_pct": "0", "acquiring_pct": "2.41"})
    return api


def row(api, nm_id=418020031):
    return next(r for r in api.get("/api/products").json() if r["nm_id"] == nm_id)


def test_wb_check(api):
    assert api.get("/api/wb/check").json()["Контент"] == "ok"


def test_row_without_cost_is_flagged(synced):
    r = row(synced)
    assert r["cost"] is None
    assert "себестоимость" in r["missing"]


def test_manual_cost_and_margin(synced):
    assert synced.put("/api/products/418020031/cost", json={"cost": "700"}).status_code == 200
    r = row(synced)
    assert r["missing"] == []
    assert r["sold_net_qty"] == 9  # 10 продаж − 1 возврат
    assert r["stock_fbo"] == 45
    cur = r["current"]
    assert cur["seller_price"] == "3073.80"
    assert cur["commission"] == "1337.10"
    assert cur["logistics"] == "483.09"  # 4 347,82 / 9
    assert cur["status"] == "ok"


def test_cost_history_latest_wins(synced):
    synced.put("/api/products/418020031/cost", json={"cost": "700"})
    synced.put("/api/products/418020031/cost", json={"cost": "800"})
    assert row(synced)["cost"] == "800.00"


def test_unknown_product_cost_404(synced):
    assert synced.put("/api/products/1/cost", json={"cost": "1"}).status_code == 404


def test_calc_price_shows_new_margin(synced):
    synced.put("/api/products/418020031/cost", json={"cost": "700"})
    synced.put("/api/products/418020031/calc-price", json={"price": "2000", "discount_pct": "40"})
    r = row(synced)
    assert r["calc"]["status"] == "loss"
    assert Decimal(r["calc"]["profit"]) < 0


def test_tax_setting_applies(synced):
    synced.put("/api/products/418020031/cost", json={"cost": "700"})
    synced.put("/api/settings", json={"tax_pct": "7"})
    assert row(synced)["current"]["tax"] == "215.17"


def test_unknown_setting_rejected(synced):
    assert synced.put("/api/settings", json={"foo": "1"}).status_code == 422


def test_promotion_analysis(synced):
    synced.put("/api/products/418020031/cost", json={"cost": "700"})
    promos = synced.get("/api/promotions").json()
    assert promos[0]["name"] == "11.11"
    a = synced.get(f"/api/promotions/{promos[0]['id']}").json()
    item = a["items"][0]
    assert item["current"]["status"] == "ok"
    assert item["promo"]["status"] == "loss"  # скидка 60% уводит в минус
    assert item["recommend"] == "не участвовать"


# --- отправка цен ---


def test_send_requires_preview_token(synced, fake_wb):
    synced.put("/api/products/418020031/calc-price", json={"price": "5300"})
    prev = synced.post("/api/prices/preview", json={}).json()
    item = prev["items"][0]
    assert (item["old_price"], item["new_price"], item["new_discount"]) == (5123, 5300, 40)
    bad = synced.post("/api/prices/send", json={"items": [_change(item)], "confirm_token": "x"})
    assert bad.status_code == 409
    assert fake_wb.uploaded == []


def test_send_and_revert(synced, fake_wb, factory):
    synced.put("/api/products/418020031/calc-price", json={"price": "5300"})
    prev = synced.post("/api/prices/preview", json={}).json()
    resp = synced.post(
        "/api/prices/send", json={"items": [_change(i) for i in prev["items"]], "confirm_token": prev["confirm_token"]}
    ).json()
    assert resp["status"] == "sent"
    assert fake_wb.uploaded == [{"data": [{"nmID": 418020031, "price": 5300, "discount": 40}]}]
    with factory() as s:
        p = s.get(Price, (1, 418020031))
        assert p.price == Decimal(5300)
        assert p.calc_price is None

    hist = synced.get("/api/prices/history").json()
    assert hist[0]["new_price"] == "5300.00"

    rev = synced.post("/api/prices/preview", json={"revert_change_ids": [hist[0]["id"]]}).json()
    assert rev["items"][0]["new_price"] == 5123
    synced.post(
        "/api/prices/send", json={"items": [_change(i) for i in rev["items"]], "confirm_token": rev["confirm_token"]}
    )
    assert fake_wb.uploaded[-1] == {"data": [{"nmID": 418020031, "price": 5123, "discount": 40}]}


def test_stale_preview_is_rejected(synced, factory, fake_wb):
    synced.put("/api/products/418020031/calc-price", json={"price": "5300"})
    prev = synced.post("/api/prices/preview", json={}).json()
    with factory() as s:  # цена в WB поменялась между предпросмотром и подтверждением
        s.get(Price, (1, 418020031)).price = Decimal(5200)
        s.commit()
    resp = synced.post(
        "/api/prices/send", json={"items": [_change(i) for i in prev["items"]], "confirm_token": prev["confirm_token"]}
    )
    assert resp.status_code == 409
    assert fake_wb.uploaded == []


def test_wb_error_is_logged(synced, fake_wb, factory):
    fake_wb.fail_upload = True
    synced.put("/api/products/418020031/calc-price", json={"price": "5300"})
    prev = synced.post("/api/prices/preview", json={}).json()
    resp = synced.post(
        "/api/prices/send", json={"items": [_change(i) for i in prev["items"]], "confirm_token": prev["confirm_token"]}
    ).json()
    assert resp["status"] == "error"
    with factory() as s:
        assert s.query(PriceChange).one().status == "error"
        assert s.get(Price, (1, 418020031)).price == Decimal(5123)  # цена в базе не поменялась


def test_invalid_discount_rejected(synced):
    synced.put("/api/products/418020031/calc-price", json={"price": "5300", "discount_pct": "99.6"})
    assert synced.post("/api/prices/preview", json={}).status_code == 422


def _change(item):
    return {k: item[k] for k in ("nm_id", "old_price", "old_discount", "new_price", "new_discount")}
