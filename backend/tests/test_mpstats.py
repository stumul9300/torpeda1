import httpx

from torpeda import mpstats


def test_summarize_daily_rows():
    by_period = [
        {"data": "2026-10-02", "sales": 3, "final_price": 900, "price": 2000, "balance": 10},
        {"data": "2026-10-01", "sales": 5, "final_price": 1000, "price": 2000, "balance": 0},
    ]
    r = mpstats.summarize(1, {"name": "Товар"}, by_period)
    assert r["name"] == "Товар"
    assert r["sales"] == 8
    assert r["revenue"] == 5 * 1000 + 3 * 900
    assert (r["price_first"], r["price_last"]) == (1000, 900)
    assert r["balance_last"] == 10
    assert r["days_out_of_stock"] == 1


def test_fetch_sends_token_header(monkeypatch, tmp_path):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/full"):
            return httpx.Response(200, json={"name": "Товар"})
        return httpx.Response(200, json=[{"date": "2026-10-01", "sales": 2, "final_price": 500, "balance": 4}])

    real_client = httpx.Client
    monkeypatch.setattr(mpstats.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(mpstats, "OUT_DIR", tmp_path)
    monkeypatch.setenv("MPSTATS_TOKEN", "secret")
    rows = mpstats.fetch([42], mpstats.date(2026, 10, 1), mpstats.date(2026, 10, 30))
    assert rows[0]["sales"] == 2
    assert all(r.headers["X-Mpstats-TOKEN"] == "secret" for r in seen)
    assert seen[1].url.path == "/api/analytics/v1/wb/items/42/by_period"
    assert (tmp_path / "42_2026-10-01_2026-10-30.json").exists()


def test_api_mpstats_report(api, monkeypatch):
    from torpeda.api import app as app_module

    seen = {}

    def fake_fetch(skus, d1, d2):
        seen["args"] = (skus, d1, d2)
        return [{"sku": skus[0], "name": "Товар", "sales": 3}]

    monkeypatch.setattr(app_module.mpstats, "fetch", fake_fetch)
    res = api.get("/api/mpstats?skus=482235433&days=7")
    assert res.status_code == 200
    assert res.json()["rows"][0]["sku"] == 482235433
    assert (seen["args"][2] - seen["args"][1]).days == 6
    assert api.get("/api/mpstats?skus=abc").status_code == 422


def test_token_from_env_file_with_bom_and_quotes(monkeypatch, tmp_path):
    (tmp_path / ".env").write_bytes('﻿MPSTATS_TOKEN="abc.def "\n'.encode())
    monkeypatch.setattr(mpstats, "BACKEND_DIR", tmp_path)
    monkeypatch.delenv("MPSTATS_TOKEN", raising=False)
    value, source = mpstats.token_source()
    assert value == "abc.def"
    assert str(tmp_path / ".env") in source
    assert "длина 7" in mpstats.describe(value, source)
    assert "abc" not in mpstats.describe(value, source)


def test_401_message_names_source_not_token(monkeypatch, tmp_path):
    import pytest

    monkeypatch.setattr(mpstats, "BACKEND_DIR", tmp_path)
    monkeypatch.setenv("MPSTATS_TOKEN", "secret.token1234")
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, text="bad")))
    with pytest.raises(mpstats.MpstatsError) as exc:
        mpstats.get(client, "items/1/full")
    assert "переменная окружения" in str(exc.value)
    assert "длина 16" in str(exc.value)
    assert "secret" not in str(exc.value)


def test_saved_token_wins_and_is_checked(api, monkeypatch, tmp_path):
    monkeypatch.setattr(mpstats.config, "KEYS_FILE", tmp_path / "keys.json")
    monkeypatch.setattr(mpstats.config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mpstats, "BACKEND_DIR", tmp_path)
    monkeypatch.setenv("MPSTATS_TOKEN", "from.env.0000")
    seen = []

    def fake_get(url, headers, timeout):
        seen.append(headers["X-Mpstats-TOKEN"])
        return httpx.Response(200, json={"available": 2500, "use": 38})

    monkeypatch.setattr(mpstats.httpx, "get", fake_get)
    res = api.put("/api/mpstats/key", json={"token": " abc.def.9876 "})
    body = res.json()
    assert body["ok"] and "осталось запросов 2462" in body["text"]
    assert body["tail"] == "9876" and "программа" in body["source"]
    assert seen == ["abc.def.9876"]
    assert "abc.def" not in res.text
    api.put("/api/mpstats/key", json={"token": ""})
    assert api.get("/api/mpstats/key").json()["source"].startswith("переменная окружения")
