import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from quantroute.service import create_app


def test_security_headers(monkeypatch):
    monkeypatch.setenv("QUANTROUTE_ENV", "development")
    monkeypatch.setenv("QUANTROUTE_AUTH_ENABLED", "false")
    with TestClient(create_app()) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert "x-request-id" in r.headers


def test_production_fails_closed_without_key(monkeypatch):
    monkeypatch.setenv("QUANTROUTE_ENV", "production")
    monkeypatch.setenv("QUANTROUTE_AUTH_ENABLED", "true")
    monkeypatch.delenv("QUANTROUTE_API_KEY", raising=False)
    monkeypatch.setenv("QUANTROUTE_ALLOWED_HOSTS", "localhost")
    with pytest.raises(RuntimeError):
        create_app()


def test_api_key_protects_v1(monkeypatch):
    monkeypatch.setenv("QUANTROUTE_ENV", "production")
    monkeypatch.setenv("QUANTROUTE_AUTH_ENABLED", "true")
    monkeypatch.setenv("QUANTROUTE_API_KEY", "a" * 40)
    monkeypatch.setenv("QUANTROUTE_ALLOWED_HOSTS", "testserver")
    monkeypatch.setenv("QUANTROUTE_DOCS_ENABLED", "false")
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/v1/algorithms").status_code == 401
        assert client.get("/v1/algorithms", headers={"X-API-Key": "a" * 40}).status_code == 200
        assert client.get("/docs").status_code in {401, 404}
