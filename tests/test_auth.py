from fastapi.testclient import TestClient

from router_core.gateway.app import create_app


def _client(config_dir, monkeypatch, tmp_path, gateway_key=None):
    monkeypatch.setenv("ROUTER_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("ROUTER_ENV", "production")
    monkeypatch.setenv("ROUTER_LEDGER_PATH", str(tmp_path / "auth.sqlite3"))
    if gateway_key is None:
        monkeypatch.delenv("ROUTER_GATEWAY_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ROUTER_GATEWAY_API_KEY", gateway_key)
    return TestClient(create_app())


def test_production_protects_inventory_and_stats(config_dir, monkeypatch, tmp_path):
    with _client(config_dir, monkeypatch, tmp_path, "gateway-secret") as client:
        assert client.get("/v1/models").status_code == 401
        assert client.get("/v1/routing/stats").status_code == 401
        assert (
            client.get("/v1/models", headers={"Authorization": "Bearer wrong"}).status_code == 401
        )


def test_production_accepts_only_the_configured_bearer(config_dir, monkeypatch, tmp_path):
    with _client(config_dir, monkeypatch, tmp_path, "gateway-secret") as client:
        headers = {"Authorization": "Bearer gateway-secret"}
        assert client.get("/v1/models", headers=headers).status_code == 200
        assert client.get("/v1/routing/stats", headers=headers).status_code == 200
        assert client.get("/dashboard", headers=headers).status_code == 200


def test_production_fails_closed_when_gateway_key_is_missing(config_dir, monkeypatch, tmp_path):
    with _client(config_dir, monkeypatch, tmp_path) as client:
        response = client.get("/v1/models")
        assert response.status_code == 503
        assert "secret" not in response.text.lower()
