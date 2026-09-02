from __future__ import annotations

import hashlib

import pytest

from rrserver import create_app
from rrserver.extensions import db
from rrserver.models import Account, PlatformAccountLink, RefreshToken


@pytest.fixture()
def secure_app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'security.sqlite3'}",
            "JWT_SECRET": "test-secret-longer-than-thirty-two-bytes",
            "RECNET_DOMAIN": "play.example.test",
            "CORS_ALLOWED_ORIGINS": ("https://admin.example.test",),
            "ALLOW_PASSWORDLESS_ACCOUNTS": False,
            "RATE_LIMIT_ENABLED": True,
        }
    )


def test_security_headers_and_restricted_cors(secure_app):
    client = secure_app.test_client()
    response = client.get("/", headers={"Origin": "https://admin.example.test"})
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Access-Control-Allow-Origin"] == "https://admin.example.test"

    rejected = client.get("/", headers={"Origin": "https://attacker.example"})
    assert "Access-Control-Allow-Origin" not in rejected.headers


def test_weak_and_passwordless_account_creation_is_rejected(secure_app):
    client = secure_app.test_client()
    empty = client.post("/connect/token", data={"grant_type": "create_account", "password": ""})
    weak = client.post(
        "/connect/token", data={"grant_type": "create_account", "password": "short"}
    )
    assert empty.status_code == 400
    assert weak.status_code == 400
    assert weak.get_json()["error"] == "invalid_request"


def test_refresh_tokens_are_hashed_at_rest_and_rotate(secure_app):
    client = secure_app.test_client()
    issued = client.post(
        "/connect/token",
        data={"grant_type": "create_account", "password": "a sufficiently long password"},
    ).get_json()
    raw_token = issued["refresh_token"]

    with secure_app.app_context():
        stored = db.session.scalar(db.select(RefreshToken))
        assert stored.token == hashlib.sha256(raw_token.encode()).hexdigest()
        assert raw_token not in stored.token

    refreshed = client.post(
        "/connect/token", data={"grant_type": "refresh_token", "refresh_token": raw_token}
    )
    reused = client.post(
        "/connect/token", data={"grant_type": "refresh_token", "refresh_token": raw_token}
    )
    assert refreshed.status_code == 200
    assert reused.status_code == 400


def test_token_endpoint_is_rate_limited(secure_app):
    client = secure_app.test_client()
    for _ in range(30):
        assert client.post(
            "/connect/token", data={"grant_type": "password", "username": "missing"}
        ).status_code == 400
    blocked = client.post(
        "/connect/token", data={"grant_type": "password", "username": "missing"}
    )
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"]


def test_cached_account_picker_requires_password(secure_app):
    from werkzeug.security import generate_password_hash

    with secure_app.app_context():
        db.session.add(Account(id=2, username="testdev", display_name="Test",
                               password_hash=generate_password_hash("test-password-123"), is_developer=True))
        db.session.flush()
        db.session.add(PlatformAccountLink(platform="0", platform_id="test-steam-id", account_id=2))
        db.session.commit()
    client = secure_app.test_client()
    for method in (client.get, client.post):
        picker = method("/cachedlogin/forplatformid/0/test-steam-id").get_json()
        assert picker[0]["accountId"] == 2
        assert picker[0]["requirePassword"] is True
        assert "password_hash" not in picker[0]
    assert client.get("/cachedlogin/forplatformid/0/unknown").get_json() == []
    assert client.post("/connect/token", data={"account_id": "2"}).status_code == 400
    assert client.post("/connect/token", data={"account_id": "2", "password": "wrong"}).status_code == 400
    assert client.post("/connect/token", data={"account_id": "2", "password": "test-password-123"}).status_code == 200
