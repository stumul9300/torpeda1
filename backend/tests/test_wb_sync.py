from datetime import datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from torpeda.db.models import CommissionRate, Price, Product, PromotionItem, ReportRow, Stock
from torpeda.sync import sync_all
from torpeda.wb_api.client import WBAuthError, WBClient

NOW = datetime(2026, 10, 24, 12, 0)


def test_token_is_sent_in_header(wb_client, fake_wb):
    wb_client.ping()
    assert all(r.headers["Authorization"] == "test-token" for r in fake_wb.requests)


def test_missing_token_has_clear_message():
    with pytest.raises(WBAuthError, match="backend/.env"):
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
        "остатки": 1,
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
        assert s.scalars(select(Stock)).one().quantity == 45
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
    assert str(result["остатки"]).startswith("ошибка")
