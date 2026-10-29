# ruff: noqa: F811
from decimal import Decimal

from test_products_api import synced  # noqa: F401

from torpeda.db.models import Price, PriceAlert


def _lower_in_wb(factory):
    """В базе цена Ольги выше, чем отдаёт WB: как будто WB сам понизил цену."""
    with factory() as s:
        s.get(Price, (1, 418020031)).price = Decimal(6000)
        s.commit()


def test_foreign_drop_is_noticed_but_not_reverted_by_default(synced, factory, fake_wb):
    _lower_in_wb(factory)
    res = synced.post("/api/prices/check").json()
    assert res["new_alerts"] == 1 and res["revert"] is None
    alert = synced.get("/api/price-alerts").json()[0]
    assert (alert["old_price"], alert["new_price"], alert["status"]) == ("6000.00", "5123.00", "new")
    assert fake_wb.uploaded == []


def test_auto_revert_sends_old_price_and_logs(synced, factory, fake_wb):
    synced.put("/api/settings", json={"revert_autopromo": "1"})
    _lower_in_wb(factory)
    res = synced.post("/api/prices/check").json()
    assert res["revert"]["reverted"] == 1
    assert fake_wb.uploaded[-1] == {"data": [{"nmID": 418020031, "price": 6000, "discount": 40}]}
    assert synced.get("/api/price-alerts").json()[0]["status"] == "reverted"
    assert synced.get("/api/prices/history").json()[0]["new_price"] == "6000.00"


def test_revert_limit_and_exclusion(synced, factory, fake_wb):
    synced.put("/api/settings", json={"revert_autopromo": "1", "revert_exclude": "418020031"})
    _lower_in_wb(factory)
    res = synced.post("/api/prices/check").json()
    assert res["revert"]["skipped"] == 1 and fake_wb.uploaded == []
    with factory() as s:
        assert s.query(PriceAlert).one().status == "skipped"


def test_manual_revert_preview(synced, factory):
    _lower_in_wb(factory)
    synced.post("/api/prices/check")
    alert = synced.get("/api/price-alerts").json()[0]
    prev = synced.post("/api/prices/preview", json={"revert_alert_ids": [alert["id"]]}).json()
    assert prev["items"][0]["new_price"] == 6000
