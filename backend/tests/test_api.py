from fastapi.testclient import TestClient

from torpeda.api.app import app

client = TestClient(app)


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_calc_unit_matches_raketa():
    resp = client.post(
        "/api/calc/unit",
        json={
            "price_before_discount": "5123",
            "discount_pct": "40",
            "cost": "700",
            "commission_pct": "43.5",
            "logistics_per_unit": "483.0912",
            "acquiring_pct": "2.41",
            "advertising_per_unit": "31.69",
            "storage_per_unit": "0.12",
            "spp_pct": "29",
            "target_margin_pct": "20",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["profit"] == "447.72"
    assert body["roi_pct"] == "63.96"
    assert body["is_loss"] is False
    assert body["target_price_before_discount"] is not None


def test_calc_unit_rejects_bad_discount():
    resp = client.post(
        "/api/calc/unit",
        json={
            "price_before_discount": "1000",
            "discount_pct": "100",
            "cost": "1",
            "commission_pct": "10",
            "logistics_per_unit": "1",
        },
    )
    assert resp.status_code == 422
