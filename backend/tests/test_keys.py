from fastapi.testclient import TestClient

from torpeda import config
from torpeda.api.app import app

client = TestClient(app)


def test_no_keys():
    assert client.get("/api/keys").json() == {"read": None, "prices": None, "info": {}}


def test_save_and_mask():
    resp = client.put("/api/keys", json={"read": "  aa.bb.secret-read-1234 \n", "prices": "aa.bb.secret-prices-9876"})
    assert resp.json()["read"] == "…1234" and resp.json()["prices"] == "…9876"
    assert "secret-read" not in client.get("/api/keys").text  # целиком ключ не показывается
    s = config.get_settings()
    assert s.wb_api_token == "aa.bb.secret-read-1234"
    assert s.wb_prices_token == "aa.bb.secret-prices-9876"


def test_update_one_keeps_other():
    client.put("/api/keys", json={"read": "a.b.aaaa1111", "prices": "a.b.bbbb2222"})
    client.put("/api/keys", json={"read": "a.b.cccc3333"})
    keys = client.get("/api/keys").json()
    assert (keys["read"], keys["prices"]) == ("…3333", "…2222")


def test_empty_removes():
    client.put("/api/keys", json={"read": "a.b.aaaa1111"})
    client.put("/api/keys", json={"read": ""})
    assert client.get("/api/keys").json()["read"] is None


def test_saved_key_wins_over_env(monkeypatch):
    monkeypatch.setenv("WB_API_TOKEN", "fromenv5555")
    assert config.get_settings().wb_api_token == "fromenv5555"
    assert client.get("/api/keys").json()["info"]["read"]["source"] == "переменная окружения Windows"
    client.put("/api/keys", json={"read": "aaa.fromfile.0000"})
    assert config.get_settings().wb_api_token == "aaa.fromfile.0000"
    assert client.get("/api/keys").json()["info"]["read"]["source"] == "программа"


def test_data_dir_on_windows(monkeypatch, tmp_path):
    monkeypatch.delenv("TORPEDA_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert config.default_data_dir() == tmp_path / "Torpeda"
    monkeypatch.setenv("TORPEDA_DATA_DIR", str(tmp_path / "my"))
    assert config.default_data_dir() == tmp_path / "my"


def test_migrate_old_data(data_dir):
    config.OLD_DATA_DIR.mkdir()
    (config.OLD_DATA_DIR / "keys.json").write_text('{"read": "old-key-7777"}', encoding="utf-8")
    (config.OLD_DATA_DIR / "torpeda.db").write_bytes(b"db")
    assert config.migrate_old_data() == ["keys.json", "torpeda.db"]
    assert config.masked_keys()["read"] == "…7777"
    assert (data_dir / "torpeda.db").read_bytes() == b"db"
    # второй раз ничего не переписывает, даже если в старой папке что-то поменялось
    (config.OLD_DATA_DIR / "keys.json").write_text('{"read": "newer-1111"}', encoding="utf-8")
    assert config.migrate_old_data() == []
    assert config.masked_keys()["read"] == "…7777"


def test_bad_key_rejected_and_logged():
    resp = client.put("/api/keys", json={"read": "не ключ"})
    assert resp.status_code == 400 and "не распознан" in resp.json()["detail"]
    import base64
    import json

    body = base64.urlsafe_b64encode(json.dumps({"acc": 3, "s": 2}).encode()).decode().rstrip("=")
    view = client.put("/api/keys", json={"read": f"aaa.{body}.sigX9z1"}).json()
    assert view["info"]["read"]["summary"][0] == "Тип ключа: Персональный"
    log = {r["section"]: r["message"] for r in client.get("/api/sync-log").json()}
    assert log["ключ: ключ для данных"] == "сохранён, окончание …X9z1, тип ключа: персональный"
