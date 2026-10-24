from fastapi.testclient import TestClient

from torpeda import config
from torpeda.api.app import app

client = TestClient(app)


def test_no_keys():
    assert client.get("/api/keys").json() == {"read": None, "prices": None}


def test_save_and_mask():
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
