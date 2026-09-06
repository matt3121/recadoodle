import pytest
from sqlalchemy.exc import OperationalError

from rrserver import create_app
from rrserver.extensions import db


@pytest.fixture()
def readiness_app(tmp_path):
    return create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'readiness.sqlite3'}",
        "JWT_SECRET": "test-secret-longer-than-thirty-two-bytes",
        "TRUSTED_HOSTS": None,
    })


def test_ready_with_database(readiness_app):
    response = readiness_app.test_client().get("/readyz")
    assert response.status_code == 200
    assert "Retry-After" not in response.headers
    assert response.get_json() == {"status": "ready", "checks": {"database": "ok"}}
    assert response.headers["Cache-Control"] == "no-store, max-age=0"


def test_health_identifies_recadoodle(readiness_app):
    response = readiness_app.test_client().get("/healthz")
    assert response.status_code == 200
    assert response.get_json() == {
        "name": "Recadoodle", "status": "ok", "gameVersion": "20230414",
    }


def test_not_ready_hides_database_details_and_recovers(readiness_app, monkeypatch):
    def unavailable():
        raise OperationalError("SELECT 1", {}, RuntimeError("private-database-details"))

    client = readiness_app.test_client()
    with readiness_app.app_context(), monkeypatch.context() as patch:
        patch.setattr(db.engine, "connect", unavailable)
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.headers["Retry-After"] == "30"
        assert response.get_json() == {
            "status": "not_ready", "checks": {"database": "unavailable"},
        }
        assert "private-database-details" not in response.get_data(as_text=True)
        assert response.headers["Cache-Control"] == "no-store, max-age=0"
        assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200


@pytest.mark.parametrize("database_available", [True, False])
def test_head_readiness_has_status_and_headers_without_body(
    readiness_app, monkeypatch, database_available,
):
    def unavailable():
        raise OperationalError("SELECT 1", {}, RuntimeError("database unavailable"))

    with readiness_app.app_context():
        if not database_available:
            monkeypatch.setattr(db.engine, "connect", unavailable)
        response = readiness_app.test_client().head("/readyz")
    assert response.status_code == (200 if database_available else 503)
    assert response.data == b""
    assert response.headers["Cache-Control"] == "no-store, max-age=0"
    assert response.headers.get("Retry-After") == (None if database_available else "30")
