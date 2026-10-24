from decimal import Decimal

from torpeda import sync
from torpeda.wb_api.site import parse_card


def test_parse_card_takes_first_size_with_price():
    data = {"products": [{"id": 1, "sizes": [{"price": None}, {"price": {"basic": 512300, "product": 215900}}]},
                         {"id": 2, "sizes": [{}]}]}  # fmt: skip
    assert parse_card(data) == {1: Decimal("2159")}


def test_sync_site_prices(api, monkeypatch):
    api.post("/api/wb/sync")
    monkeypatch.setattr(sync, "get_site_prices", lambda nms: {nm: Decimal("2159") for nm in nms})
    assert api.post("/api/wb/sync-site-prices").json() == {"products": 1}
    row = api.get("/api/products").json()[0]
    assert Decimal(str(row["site_price"])) == 2159 and row["site_price_at"]
    api.post("/api/wb/sync")  # обычная загрузка цен не стирает цену на сайте
    assert api.get("/api/products").json()[0]["site_price"] is not None
