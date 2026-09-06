from rrserver import create_app
from rrserver.routes import server_info


def test_server_info_without_database(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(server_info, "monotonic", lambda: clock[0])
    monkeypatch.setattr(server_info, "version", lambda name: "1.2.3")
    monkeypatch.setattr(server_info, "_utc_now", lambda: "2026-09-06T12:34:56Z")
    app = create_app({
        "TESTING": True,
        "JWT_SECRET": "test-secret-longer-than-thirty-two-bytes",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "TRUSTED_HOSTS": None,
    }, initialize_database=False)
    client = app.test_client()
    clock[0] = 165.9
    response = client.get("/api/server-info")
    assert response.status_code == 200
    assert response.get_json() == {
        "name": "Recadoodle", "version": "1.2.3",
        "gameVersion": "20230414", "serverTimeUtc": "2026-09-06T12:34:56Z",
        "uptimeSeconds": 65,
    }
    assert response.headers["Cache-Control"] == "no-store, max-age=0"
    clock[0] = 170.0
    assert client.get("/api/server-info").get_json()["uptimeSeconds"] == 70
    assert client.head("/api/server-info").data == b""


def test_server_info_without_installed_package(monkeypatch):
    def missing_version(name):
        raise server_info.PackageNotFoundError(name)

    monkeypatch.setattr(server_info, "version", missing_version)
    app = create_app({
        "TESTING": True,
        "JWT_SECRET": "test-secret-longer-than-thirty-two-bytes",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "TRUSTED_HOSTS": None,
    }, initialize_database=False)
    assert app.test_client().get("/api/server-info").get_json()["version"] == "unknown"


def test_status_page_has_api_label(monkeypatch):
    monkeypatch.setattr(server_info, "version", lambda name: "1.2.3")
    app = create_app({
        "TESTING": True,
        "JWT_SECRET": "test-secret-longer-than-thirty-two-bytes",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "TRUSTED_HOSTS": None,
    }, initialize_database=False)
    response = app.test_client().get("/status")
    assert response.status_code == 200
    assert b"RecadoodleAPI" in response.data
    assert b"Online" in response.data
