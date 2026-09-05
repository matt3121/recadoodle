"""Authentication and token lifecycle endpoints."""

from __future__ import annotations

import logging
import secrets

from flask import Flask, current_app, jsonify, request
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from ..auth import GAME_VERSION, consume_refresh_token, oauth_error, require_account, token_response
from ..extensions import db
from ..models import Account, PlatformAccountLink, Presence
from ..security import password_problem

auth_log = logging.getLogger("rrserver.access")


def register_authentication_routes(app: Flask) -> None:
    @app.get("/eac/challenge")
    def eac_challenge():
        return '"AA=="', 200, {"Content-Type": "text/plain"}

    @app.route("/cachedlogin/forplatformid/<platform>/<platform_id>", methods=["GET", "POST"])
    def cached_login(platform: str, platform_id: str):
        accounts = db.session.scalars(
            db.select(Account).join(PlatformAccountLink, PlatformAccountLink.account_id == Account.id)
            .where(PlatformAccountLink.platform == platform, PlatformAccountLink.platform_id == platform_id)
            .order_by(Account.id)
        ).all()
        if accounts:
            return jsonify([
                {
                    "platform": int(platform),
                    "platformId": platform_id,
                    "accountId": account.id,
                    "lastLoginTime": account.created_at.isoformat(),
                    "requirePassword": True,
                }
                for account in accounts
            ])
        if platform == "1" and platform_id == "1":
            return jsonify(
                [
                    {
                        "platform": 1,
                        "platformId": "1",
                        "accountId": 1,
                        "lastLoginTime": "2026-07-19T17:13:29.225Z",
                        "requirePassword": True,
                    }
                ]
            )
        return jsonify([])

    @app.post("/cachedlogin/forplatformids")
    def cached_logins():
        return jsonify([])

    @app.post("/connect/token")
    def connect_token():
        body = request.form if request.form else (request.get_json(silent=True) or {})
        grant = body.get("grant_type", "password")
        version = body.get("version") or body.get("ver") or GAME_VERSION

        if grant == "create_account":
            password = str(body.get("password", ""))
            create_as_developer = current_app.config["CREATE_DEVELOPER_ACCOUNTS_ON_LOGIN"]
            problem = password_problem(
                password, allow_empty=current_app.config["ALLOW_PASSWORDLESS_ACCOUNTS"]
            )
            if problem:
                auth_log.warning("AUTH rejected flow=create_account reason=password_policy password_supplied=%s", bool(password))
                return oauth_error(problem, error="invalid_request")
            account = Account(
                username=f"Player{secrets.randbelow(90_000_000) + 10_000_000}",
                display_name="New Player",
                password_hash=generate_password_hash(password) if password else "",
                is_developer=create_as_developer,
                is_moderator=create_as_developer,
                token_balance=current_app.config["STARTING_TOKENS"],
            )
            db.session.add(account)
            db.session.flush()
            account.display_name = account.username
            db.session.add(
                Presence(
                    account_id=account.id,
                    room_id=13,
                    room_instance_id=-2,
                    device_class=int(body.get("deviceClass", 0) or 0),
                )
            )
            response = token_response(account, version)
            db.session.commit()
            return jsonify(response)

        if grant == "refresh_token":
            stored = consume_refresh_token(str(body.get("refresh_token", "")))
            if stored is None:
                auth_log.warning("AUTH rejected flow=refresh_token reason=invalid_or_expired_token")
                return oauth_error("invalid refresh token")
            account = db.session.get(Account, stored.account_id)
            db.session.delete(stored)
        else:
            identity = str(body.get("username") or body.get("account_id") or "")[:128]
            account = None
            if identity.isdigit():
                account = db.session.get(Account, int(identity))
            else:
                account = db.session.scalar(
                    db.select(Account).where(func.lower(Account.username) == identity.lower())
                )
            supplied_password = str(body.get("password", ""))[:257]
            password_is_valid = account is not None and (
                check_password_hash(account.password_hash, supplied_password)
                if account.password_hash
                else supplied_password == "" and current_app.config["ALLOW_PASSWORDLESS_ACCOUNTS"]
            )
            if not password_is_valid:
                auth_log.warning(
                    "AUTH rejected flow=login account_found=%s password_supplied=%s stored_password=%s",
                    account is not None, bool(supplied_password), bool(account and account.password_hash),
                )
                return oauth_error("invalid account_id or password")

        if account is None:
            return oauth_error("account no longer exists")
        response = token_response(account, version)
        db.session.commit()
        return jsonify(response)

    @app.post("/account/me/changepassword")
    @require_account
    def change_password(account: Account):
        body = request.form if request.form else (request.get_json(silent=True) or {})
        old = str(body.get("oldPassword", ""))
        new = str(body.get("newPassword", ""))
        problem = password_problem(new)
        if problem:
            return jsonify(success=False, error=problem), 400
        if account.password_hash and not check_password_hash(account.password_hash, old):
            return jsonify(success=False, error="Your old password is incorrect."), 400
        account.password_hash = generate_password_hash(new)
        db.session.commit()
        return jsonify(success=True)
