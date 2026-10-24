"""«Что пошло не так»: журнал загрузки и проверка остатков."""

import httpx

from torpeda.diagnose import check_stocks, explain
from torpeda.sync import sync_all
from torpeda.wb_api.client import WBClient


def test_diagnose_ok(api):
    res = api.get("/api/wb/diagnose/stocks").json()
    assert [r["rows"] for r in res] == [1, 1]
    assert res[0]["explanation"].startswith("Всё в порядке")
    assert "stocks-report/wb-warehouses" in res[0]["request"]


def test_diagnose_errors():
    def handler(request):
        if "seller" in request.url.path:
            return httpx.Response(401, json={"title": "unauthorized", "detail": "token type is not allowed"})
        return httpx.Response(204)

    client = WBClient("t", transport=httpx.MockTransport(handler), sleep=lambda _: None)
    fbo, fbs = check_stocks(client)
    assert fbo["rows"] == 0 and "список пустой" in fbo["explanation"]
    assert "тип ключа" in fbs["explanation"] and fbs["status"] == 401
    assert "категории «Аналитика»" in explain(403, '{"detail":"scope not allowed"}', None)


def test_sync_log_and_unexpected_answer(api, factory):
    def handler(request):
        if "stocks-report" in request.url.path:
            return httpx.Response(200, json={"data": ["неожиданный формат"]})
        return httpx.Response(200, json={})

    client = WBClient("t", transport=httpx.MockTransport(handler), sleep=lambda _: None)
    result = sync_all(client, factory)
    assert result["остатки FBO"].startswith("ошибка: AttributeError")  # не уронило всю загрузку
    assert result["товары"] == 0
    log = {r["section"]: r for r in api.get("/api/sync-log").json()}
    assert log["остатки FBO"]["ok"] is False
    assert log["товары"]["ok"] is True
