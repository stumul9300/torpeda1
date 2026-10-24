import pytest
from fastapi.testclient import TestClient

from torpeda import config
from torpeda.api.app import app


@pytest.fixture(autouse=True)
def keys_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "KEYS_FILE", tmp_path / "keys.json")
    monkeypatch.delenv("WB_API_TOKEN", raising=False)
    monkeypatch.delenv("WB_PRICES_TOKEN", raising=False)
    return tmp_path / "keys.json"


client = TestClient(app)


def test_no_keys():
    assert client.get("/api/keys").json() == {"read": None, "prices": None}


def test_save_and_mask(keys_file):
    resp = client.put("/api/keys", json={"read": "  secret-read-1234 ", "prices": "secret-prices-9876"})
    assert resp.json() == {"read": "…1234", "prices": "…9876"}
    assert "secret-read" not in client.get("/api/keys").text  # целиком ключ не показывается
    s = config.get_settings()
    assert s.wb_api_token == "secret-read-1234"
    assert s.wb_prices_token == "secret-prices-9876"


def test_update_one_keeps_other():
    client.put("/api/keys", json={"read": "aaaa1111", "prices": "bbbb2222"})
    client.put("/api/keys", json={"read": "cccc3333"})
    assert client.get("/api/keys").json() == {"read": "…3333", "prices": "…2222"}


def test_empty_removes():
    client.put("/api/keys", json={"read": "aaaa1111"})
    client.put("/api/keys", json={"read": ""})
    assert client.get("/api/keys").json()["read"] is None


def test_env_wins(monkeypatch):
    client.put("/api/keys", json={"read": "fromfile0000"})
    monkeypatch.setenv("WB_API_TOKEN", "fromenv5555")
    assert config.get_settings().wb_api_token == "fromenv5555"
