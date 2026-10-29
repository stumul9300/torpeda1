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
    assert r["stock_fbs"] == 7
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


def test_product_row_has_best_promo(synced, factory):
    from datetime import datetime, timedelta

    from torpeda.db.models import Promotion

    synced.put("/api/products/418020031/cost", json={"cost": "700"})
    with factory() as s:  # акция из тестовых данных должна идти прямо сейчас
        for p in s.query(Promotion):
            p.start_at, p.end_at = datetime.now() - timedelta(days=1), datetime.now() + timedelta(days=5)
        s.commit()
    r = row(synced)
    assert r["promo_best"]["name"] == "11.11"
    assert r["promo_best"]["status"] == "loss"
    assert r["promo_best"]["price"]
    assert r["promo_current"] in (None, "11.11")


def _promo_now(factory):
    from datetime import datetime, timedelta

    from torpeda.db.models import Promotion

    with factory() as s:
        for p in s.query(Promotion):
            p.start_at, p.end_at = datetime.now() - timedelta(days=1), datetime.now() + timedelta(days=5)
        s.commit()


def test_recalc_skips_loss_promo(synced, factory):
    synced.put("/api/products/418020031/cost", json={"cost": "700"})
    _promo_now(factory)
    res = synced.post("/api/prices/recalc-promos").json()
    assert res["loss"] == 1 and res["changed"] == 0  # скидка 60% уводит в минус
    assert row(synced)["calc_price"] is None


def test_recalc_sets_new_price_by_promo(synced, factory):
    from decimal import Decimal

    from torpeda.db.models import PromotionItem

    synced.put("/api/products/418020031/cost", json={"cost": "700"})
    _promo_now(factory)
    with factory() as s:  # акция с небольшой скидкой: маржа остаётся положительной
        for it in s.query(PromotionItem):
            it.plan_price, it.plan_discount_pct = Decimal(5200), Decimal(40)
        s.commit()
    res = synced.post("/api/prices/recalc-promos").json()
    assert res["changed"] == 1
    r = row(synced)
    assert (Decimal(r["calc_price"]), Decimal(r["calc_discount_pct"])) == (5200, 40)
    assert synced.get("/api/prices/history").json() == []  # в WB ничего не отправлено


def test_best_promo_is_highest_price_without_loss(synced, factory):
    from datetime import datetime, timedelta
    from decimal import Decimal

    from torpeda.db.models import Promotion, PromotionItem

    synced.put("/api/products/418020031/cost", json={"cost": "700"})
    _promo_now(factory)
    with factory() as s:
        s.add(Promotion(account_id=1, id=2002, name="Дорогая", type="regular", start_at=datetime.now(),
                        end_at=datetime.now() + timedelta(days=3)))
        s.add(PromotionItem(account_id=1, promotion_id=2002, nm_id=418020031, in_action=False,
                            plan_price=Decimal(5300), plan_discount_pct=Decimal(40)))
        s.add(Promotion(account_id=1, id=2003, name="Дешёвая", type="regular", start_at=datetime.now(),
                        end_at=datetime.now() + timedelta(days=3)))
        s.add(PromotionItem(account_id=1, promotion_id=2003, nm_id=418020031, in_action=False,
                            plan_price=Decimal(5200), plan_discount_pct=Decimal(40)))
        s.commit()
    r = row(synced)
    assert r["promo_best"]["name"] == "Дорогая"  # 11.11 убыточная и не выбирается
    assert len(r["promos"]) == 3


def test_promo_note_explains_empty_cells(synced, factory):
    from torpeda.db.models import Promotion, PromotionItem

    _promo_now(factory)
    assert row(synced)["promo_note"] is None  # цена для вступления есть
    with factory() as s:  # у товара не осталось акций
        s.query(PromotionItem).delete()
        s.commit()
    assert "из файлов" in row(synced)["promo_note"]
    with factory() as s:  # акции не загружены совсем
        s.query(Promotion).delete()
        s.commit()
    assert "не загружены" in row(synced)["promo_note"]


def test_promo_advice_lower_price(synced, factory):
    from decimal import Decimal

    from torpeda.db.models import PromotionItem

    synced.put("/api/products/418020031/cost", json={"cost": "700"})
    _promo_now(factory)
    best = row(synced)["promo_best"]
    assert Decimal(best["cur_seller_price"]) == Decimal("3073.80")
    assert Decimal(best["delta_seller"]) < 0  # плановая цена 11.11 ниже нынешней
    assert best["advice"].startswith("понизить цену продавца")
    assert "убыток" in best["advice"]
    with factory() as s:  # цена акции выше нынешней: снижать не нужно
        for it in s.query(PromotionItem):
            it.plan_price, it.plan_discount_pct = Decimal(6000), Decimal(40)
        s.commit()
    assert "без снижения" in row(synced)["promo_best"]["advice"]


def test_recalc_skips_without_cost(synced, factory):
    _promo_now(factory)
    assert synced.post("/api/prices/recalc-promos").json()["no_cost"] == 1


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
