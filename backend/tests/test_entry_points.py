"""Точки входа из отчёта кабинета WB."""

from tests.test_costs_excel import xlsx

HEAD = ("Артикул WB", "Артикул продавца", "Точка входа", "Дата", "Показы", "Переходы в карточку", "CTR, %")


def test_import_and_summary(api):
    data = xlsx(
        ("Точки входа за период",),
        HEAD,
        (111, "a", "Поиск", "27.10.2026", 100, 10, 10),
        (111, "a", "Поиск", "28.10.2026", 300, 50, 20),
        (111, "a", "Каталог", "28.10.2026", 50, 5, 10),
        (222, "b", "Поиск", "28.10.2026", 10, 1, 10),
    )
    body = api.post("/api/entry-points/import", files=[("files", ("т.xlsx", data)), ("files", ("bad.xlsx", b"x"))]).json()
    assert body["rows"] == 4 and any("error" in f for f in body["files"])

    res = api.get("/api/entry-points", params={"nm_id": 111}).json()
    assert res["columns"] == ["Показы", "Переходы в карточку", "CTR, %"]
    search = next(r for r in res["rows"] if r["point"] == "Поиск")
    assert (search["m0"], search["m1"], search["m2"]) == (400, 60, 15)  # показы складываются, CTR усредняется
    assert len(res["rows"]) == 2 and res["date_from"] == "2026-10-27"

    # повторная загрузка того же дня заменяет данные, а не удваивает
    again = xlsx(HEAD, (111, "a", "Поиск", "28.10.2026", 1, 1, 1))
    api.post("/api/entry-points/import", files=[("files", ("т.xlsx", again))])
    res = api.get("/api/entry-points", params={"nm_id": 111}).json()
    assert next(r for r in res["rows"] if r["point"] == "Поиск")["m0"] == 101
    assert len(api.get("/api/entry-points").json()["rows"]) == 3


def test_not_a_report(api):
    body = api.post("/api/entry-points/import", files=[("files", ("x.xlsx", xlsx(("a", "b"), (1, 2))))]).json()
    assert "Артикул WB" in body["files"][0]["error"]
