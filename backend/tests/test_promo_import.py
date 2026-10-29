"""Акции из файлов кабинета WB."""

from tests.test_costs_excel import xlsx

HEAD = ("Товар уже участвует в акции", "Артикул WB", "Плановая цена для акции", "Текущая розничная цена",
        "Загружаемая скидка для участия в акции")  # fmt: skip
NAME = "Все товары подходящие для акции_11.11_ хиты автоматические скидки_29.10.2026 11.05.17.xlsx"


def test_promo_name():
    from torpeda.promo_import import promo_name

    assert promo_name(NAME) == ("11.11_ хиты", "auto")
    assert promo_name("Товары для акции_11.11_29.10.2026 11.04.44.xlsx") == ("11.11", "regular")


def test_import_feeds_best_promo(api):
    api.post("/api/wb/sync")
    api.put("/api/products/418020031/cost", json={"cost": "100"})
    data = xlsx(HEAD, ("Нет", 418020031, 900, 3000, "71"), ("Нет", 111, 900, 3000, "71"))
    resp = api.post("/api/promotions/import", files=[("files", (NAME, data)), ("files", ("bad.xlsx", b"x"))])
    body = resp.json()
    assert body["promotions"] == 1 and body["items"] == 2
    assert "error" in body["files"][1]

    rows = api.get("/api/promotions-best").json()
    assert [r["nm_id"] for r in rows] == [418020031]
    mine = next(p for p in rows[0]["promos"] if p["name"] == "11.11_ хиты")
    assert float(mine["discount_pct"]) == 71

    # повторная загрузка заменяет данные акции, а не дублирует
    api.post("/api/promotions/import", files=[("files", (NAME, xlsx(HEAD, ("Нет", 418020031, 800, 3000, "74"))))])
    again = api.get("/api/promotions-best").json()[0]["promos"]
    assert next(p for p in again if p["name"] == "11.11_ хиты")["discount_pct"] in ("74.00", "74.000")
