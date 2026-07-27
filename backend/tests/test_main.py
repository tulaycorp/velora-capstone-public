from fastapi.testclient import TestClient

from app import main


def test_app_shutdown_disposes_database_pool(monkeypatch) -> None:
    dispose_calls: list[bool] = []
    monkeypatch.setattr(main.settings, "auto_create_schema", False)
    monkeypatch.setattr(main.engine, "dispose", lambda: dispose_calls.append(True))

    with TestClient(main.create_app()) as client:
        assert client.get("/health").status_code == 200

    assert dispose_calls == [True]


def test_cors_allows_only_configured_origin_methods_and_headers(monkeypatch) -> None:
    monkeypatch.setattr(main.settings, "cors_origins", ["https://app.example"])
    monkeypatch.setattr(main.settings, "auto_create_schema", False)
    monkeypatch.setattr(main.engine, "dispose", lambda: None)

    with TestClient(main.create_app()) as client:
        allowed = client.options(
            "/session-context",
            headers={
                "Origin": "https://app.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization,X-Request-ID",
            },
        )
        denied = client.options(
            "/session-context",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        exposed = client.get(
            "/health",
            headers={"Origin": "https://app.example"},
        )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://app.example"
    assert "authorization" in allowed.headers["access-control-allow-headers"].lower()
    assert exposed.headers["access-control-expose-headers"] == "X-Request-ID"
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers
