import httpx


def test_photo_cached_once(api, monkeypatch):
    api.post("/api/wb/sync")
    row = api.get("/api/products").json()[0]
    assert row["photo"] == f"/api/photos/{row['nm_id']}"
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return httpx.Response(200, content=b"jpg", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    assert api.get(row["photo"]).content == b"jpg"
    assert api.get(row["photo"]).content == b"jpg"
    assert calls == ["https://img.example/tm.webp"]


def test_photo_missing_is_404(api, monkeypatch):
    api.post("/api/wb/sync")
    row = api.get("/api/products").json()[0]

    def broken(url, **kw):
        raise httpx.ConnectError("нет связи")

    monkeypatch.setattr(httpx, "get", broken)
    assert api.get(row["photo"]).status_code == 404
    assert api.get("/api/photos/1").status_code == 404


def test_products_have_last_spp(api):
    api.post("/api/wb/sync")
    row = api.get("/api/products").json()[0]
    assert float(row["spp"]) == 29


def test_sync_spp_button(api):
    api.post("/api/wb/sync")
    assert api.post("/api/wb/sync-spp").json()["orders"] >= 1
    row = api.get("/api/products").json()[0]
    assert row["spp_at"]
