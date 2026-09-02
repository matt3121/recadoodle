from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from functools import wraps

import jwt
from flask import current_app, jsonify, request

from .extensions import db
from .models import Account, RefreshToken

GAME_VERSION = "20230414"


def issue_access_token(account: Account, version: str | None = None) -> str:
    now = datetime.now(UTC)
    roles = ["gameClient", "screenshare"]
    if account.is_developer:
        roles.append("developer")
    if account.is_moderator:
        roles.append("moderator")
    payload = {
        "sub": str(account.id),
        "jti": secrets.token_urlsafe(16),
        "iat": now,
        "exp": now + timedelta(seconds=current_app.config["TOKEN_TTL_SECONDS"]),
        "role": roles,
        "rn.ver": version or GAME_VERSION,
        "rn.platform": 0,
        "rn.platformid": "",
    }
    return jwt.encode(payload, current_app.config["JWT_SECRET"], algorithm="HS256")


def issue_refresh_token(account: Account) -> str:
    value = secrets.token_urlsafe(48)
    db.session.add(RefreshToken(token=_refresh_token_digest(value), account_id=account.id))
    return value


def _refresh_token_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def consume_refresh_token(value: str) -> RefreshToken | None:
    """Look up a hashed token, with a compatibility fallback for old databases."""

    stored = db.session.get(RefreshToken, _refresh_token_digest(value))
    if stored is None:
        stored = db.session.get(RefreshToken, value)
    if stored is None:
        return None
    created_at = stored.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    max_age = timedelta(seconds=current_app.config["REFRESH_TOKEN_TTL_SECONDS"])
    if datetime.now(UTC) - created_at > max_age:
        db.session.delete(stored)
        db.session.commit()
        return None
    return stored


def token_response(account: Account, version: str | None = None) -> dict:
    return {
        "access_token": issue_access_token(account, version),
        "expires_in": current_app.config["TOKEN_TTL_SECONDS"],
        "token_type": "Bearer",
        "refresh_token": issue_refresh_token(account),
        "scope": "openid profile offline_access",
        "key": "8oQ+e+WQaOBPbEcakhqs3dwZZdOmmyDUmJSD9u4AHMY=",
    }


def current_account() -> Account | None:
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    try:
        payload = jwt.decode(
            header.split(" ", 1)[1],
            current_app.config["JWT_SECRET"],
            algorithms=["HS256"],
            options={"require": ["exp", "iat", "sub"]},
        )
        return db.session.get(Account, int(payload["sub"]))
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        return None


def require_account(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        account = current_account()
        if account is None:
            return "", 401
        return view(account, *args, **kwargs)

    return wrapped


def oauth_error(description: str, error: str = "invalid_grant", status: int = 400):
    return jsonify(error=error, error_description=description), status
