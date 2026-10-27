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
