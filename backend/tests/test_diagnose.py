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


def test_token_info_hides_ids():
    import base64
    import json

    from torpeda.diagnose import token_info

    payload = {"exp": 4102444800, "s": (1 << 30) | 0b110, "acc": 1, "oid": 12345, "uid": 777, "t": False}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    info = token_info(f"aaa.{body}.sig")
    assert info["ok"] is False and "«Базовый»" in info["text"]
    assert info["summary"][0] == "Тип ключа: Базовый"
    assert "Категории: Контент, Аналитика" in info["summary"] and "Только чтение: да" in info["summary"]
    assert info["claims"]["oid"] == "скрыто" and info["claims"]["uid"] == "скрыто"
    assert info["claims"]["acc"] == 1 and "2100" in info["claims"]["exp"]
    assert "биты: 1, 2, 30" in info["claims"]["s"]
    assert token_info("not-a-jwt")["ok"] is False
    personal = base64.urlsafe_b64encode(json.dumps({"acc": 3, "s": 2}).encode()).decode().rstrip("=")
    info = token_info(f"aaa.{personal}.sig")
    assert info["ok"] is True and info["summary"][0] == "Тип ключа: Персональный"
