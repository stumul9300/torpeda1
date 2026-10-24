from decimal import Decimal


def _costs(api):
    return {p["nm_id"]: p.get("cost") for p in api.get("/api/products").json()}


def test_bulk_cost_only_empty_and_undo(api):
    api.post("/api/wb/sync")
    nm = next(iter(_costs(api)))
    api.put(f"/api/products/{nm}/cost", json={"cost": 300})
    assert api.post("/api/costs/bulk", json={"cost": 700, "only_empty": True}).json() == {"written": 0}

    assert api.post("/api/costs/bulk", json={"cost": 700, "only_empty": False}).json() == {"written": 1}
    assert Decimal(str(_costs(api)[nm])) == 700
    assert api.post("/api/costs/undo").json() == {"restored": 1}
    assert Decimal(str(_costs(api)[nm])) == 300
    assert api.post("/api/costs/undo").status_code == 400
