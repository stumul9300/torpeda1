import json
from datetime import datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine, inspect, select, text

from torpeda.db import init_db
from torpeda.db.models import CommissionRate, Price, Product, PromotionItem, ReportRow, Stock
from torpeda.sync import sync_all, sync_stocks
from torpeda.wb_api.client import WBAuthError, WBClient

NOW = datetime(2026, 10, 24, 12, 0)


def test_token_is_sent_in_header(wb_client, fake_wb):
    wb_client.ping()
    assert all(r.headers["Authorization"] == "test-token" for r in fake_wb.requests)


def test_missing_token_has_clear_message():
    with pytest.raises(WBAuthError, match="Настройки"):
        WBClient("")


def test_ping_reports_each_service(wb_client):
    assert set(wb_client.ping().values()) == {"ok"}


def test_ping_shows_which_category_is_missing():
    def handler(request):
        if "statistics" in request.url.host:
            return httpx.Response(401, text="token scope not allowed")
        return httpx.Response(200, json={})

    client = WBClient("t", transport=httpx.MockTransport(handler))
    result = client.ping()
    assert result["Контент"] == "ok"
    assert "401" in result["Статистика"]


def test_retries_on_429():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429, headers={"X-Ratelimit-Retry": "2"})
        return httpx.Response(200, json={"report": []})

    slept = []
    client = WBClient("t", transport=httpx.MockTransport(handler), sleep=slept.append)
    assert client.get_commissions() == []
    assert slept == [2.0, 2.0]


def test_sync_all_fills_database(wb_client, factory):
    result = sync_all(wb_client, factory, now=NOW)
    assert result == {
        "товары": 1,
        "цены": 1,
        "комиссии": 1,
        "остатки FBO": 1,
        "остатки FBS": 1,
        "заказы": 1,
        "продажи": 1,
        "финотчёт": 13,
        "акции": (1, 1),
    }
    with factory() as s:
        p = s.get(Product, (1, 418020031))
        assert p.subject_id == 192
        assert p.volume_l == Decimal("2.625")
        price = s.get(Price, (1, 418020031))
        assert (price.price, price.discount_pct) == (Decimal(5123), Decimal(40))
        rate = s.get(CommissionRate, 192)
        assert (rate.fbo_pct, rate.fbs_pct) == (Decimal("43.5"), Decimal(48))
        stocks = {st.scheme: st.quantity for st in s.scalars(select(Stock))}
        assert stocks == {"FBO": 45, "FBS": 7}
        assert len(s.scalars(select(ReportRow)).all()) == 13
        item = s.scalars(select(PromotionItem)).one()
        assert item.plan_discount_pct == Decimal(60)


def test_sync_keeps_calc_price(wb_client, factory):
    sync_all(wb_client, factory, now=NOW)
    with factory() as s:
        s.get(Price, (1, 418020031)).calc_price = Decimal(5200)
        s.commit()
    sync_all(wb_client, factory, now=NOW)
    with factory() as s:
        assert s.get(Price, (1, 418020031)).calc_price == Decimal(5200)


def test_sync_continues_after_one_section_fails(factory):
    def handler(request):
        if "statistics" in request.url.host:
            return httpx.Response(401, text="no scope")
        return httpx.Response(200, json={})

    client = WBClient("t", transport=httpx.MockTransport(handler), sleep=lambda _: None)
    result = sync_all(client, factory, now=NOW)
    assert result["товары"] == 0
    assert str(result["заказы"]).startswith("ошибка: у ключа нет доступа, включите категорию «Статистика»")


def test_stocks_paging_and_resync(factory):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append((request.url.path.rsplit("/", 1)[1], body["offset"]))
        n = 2 if body["offset"] == 0 else 1  # первая страница полная, вторая короче
        items = [{"nmId": 1, "warehouseName": "Склад WB", "quantity": 5}] * n
        return httpx.Response(200, json={"data": {"items": items}})

    client = WBClient("t", transport=httpx.MockTransport(handler), sleep=lambda _: None)
    assert list(client.iter_stocks("wb", page_size=2)) and calls == [("wb-warehouses", 0), ("wb-warehouses", 2)]
    with factory() as s:
        assert sync_stocks(client, s, NOW, "FBS") == 2  # page_size по умолчанию большой — одна страница
        assert sync_stocks(client, s, NOW, "FBS") == 2  # повторная загрузка заменяет снимок
        s.commit()
        assert len(s.scalars(select(Stock).where(Stock.scheme == "FBS")).all()) == 2


def test_old_stocks_table_is_recreated(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE stocks (id INTEGER PRIMARY KEY, nm_id INTEGER, quantity INTEGER)"))
    init_db(engine)
    assert "scheme" in {c["name"] for c in inspect(engine).get_columns("stocks")}


def test_sync_summary_and_progress(api):
    from torpeda.api import app as app_module

    res = api.post("/api/wb/sync").json()
    lines = {line.split(":")[0]: line for line in res["summary"]}
    assert lines["остатки FBO"].startswith("остатки FBO: получено ")
    assert "строк" in lines["остатки FBO"]
    progress = api.get("/api/wb/sync-progress").json()
    assert progress["running"] is False and progress["total"] == len(res["summary"])
    assert progress["done"] == res["summary"]
    assert app_module.SYNC_PROGRESS["index"] == progress["total"]


def test_describe():
    from torpeda.sync import describe

    assert describe("остатки FBS", 0).endswith("нажмите «Проверить остатки» в «Настройках»)")
    assert describe("заказы", 1234) == "заказы: получено 1 234 заказов"
    assert describe("акции", (2, 10)) == "акции: получено акций 2, товаров в них 10"
    assert describe("цены", "ошибка: нет доступа") == "цены: ошибка: нет доступа"


def test_static_not_cached(api):
    resp = api.get("/")
    assert resp.headers.get("cache-control") == "no-cache"
    assert api.get("/api/info").json()["version"]


def test_base_token_stocks_fallback(api, factory, fake_wb):
    from sqlalchemy import select

    from torpeda.db.models import Stock

    fake_wb.base_token = True
    res = api.post("/api/wb/sync").json()
    lines = {line.split(":")[0]: line for line in res["summary"]}
    assert lines["остатки FBO"] == "остатки FBO: получено 3 строк"
    assert "«Персональный»" in lines["остатки FBS"] and "ошибка" in lines["остатки FBS"]
    assert "включите категорию" not in lines["остатки FBS"]
    with factory() as s:
        stocks = list(s.scalars(select(Stock).where(Stock.scheme == "FBO")))
    assert sum(x.quantity for x in stocks) == 45
    assert sum(x.in_way_to_client for x in stocks) == 3
    assert {x.warehouse for x in stocks} == {"Коледино", "Тула", "в пути"}


def test_diagnose_explains_base_token(api, fake_wb):
    fake_wb.base_token = True
    checks = api.get("/api/wb/diagnose/stocks").json()
    assert all("«Базовый»" in c["explanation"] for c in checks)
