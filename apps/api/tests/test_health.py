from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.routers.health import DependencyCheck


def test_health_ok(client: TestClient) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["service"] == "freelancer-os-api"
    assert res.headers["X-Request-ID"]
    assert res.headers["X-Content-Type-Options"] == "nosniff"


def test_request_id_is_echoed_when_valid_and_replaced_when_not(client: TestClient) -> None:
    assert client.get("/health", headers={"X-Request-ID": "abc-123"}).headers["X-Request-ID"] == (
        "abc-123"
    )
    replaced = client.get("/health", headers={"X-Request-ID": "bad id with spaces"})
    assert replaced.headers["X-Request-ID"] != "bad id with spaces"


def test_ready_reports_dependency_state(client: TestClient) -> None:
    with patch("app.routers.health._check_redis", return_value=DependencyCheck(status="ok")):
        res = client.get("/ready")
    assert res.status_code == 200
    assert res.json() == {
        "status": "ready",
        "checks": {
            "database": {"status": "ok", "detail": None},
            "redis": {"status": "ok", "detail": None},
        },
    }


def test_ready_returns_503_without_leaking_details(client: TestClient) -> None:
    down = DependencyCheck(status="error", detail="ConnectionError")
    with patch("app.routers.health._check_redis", return_value=down):
        res = client.get("/ready")
    assert res.status_code == 503
    assert res.json()["status"] == "not_ready"
    assert "redis://" not in res.text


def test_openapi_lists_health_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/health" in paths and "/ready" in paths
