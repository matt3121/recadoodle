from __future__ import annotations

import logging
import os
import secrets
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask, jsonify, request
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config
from .extensions import db, sock
from .notifications import register_notification_hub
from .routes import register_routes
from .security import register_security

INSECURE_SECRET_VALUES = {
    "",
    "development-only-change-me",
    "replace-me-with-a-long-random-value",
}


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    configured_secret = str(app.config.get("JWT_SECRET", ""))
    if configured_secret in INSECURE_SECRET_VALUES or len(configured_secret) < 32:
        secret_path = Path(app.instance_path) / "jwt_secret"
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        if not secret_path.exists():
            descriptor = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as secret_file:
                secret_file.write(secrets.token_urlsafe(48))
        app.config["JWT_SECRET"] = secret_path.read_text(encoding="utf-8").strip()
    app.secret_key = app.config["JWT_SECRET"]

    if app.config["TRUST_CLOUDFLARE_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    sock.init_app(app)
    register_security(app)
    register_notification_hub(sock)
    register_routes(app)

    access_logger = logging.getLogger("rrserver.access")
    access_logger.setLevel(logging.INFO)
    if not access_logger.handlers:
        access_log_path = Path(app.instance_path) / "access.log"
        access_log_path.parent.mkdir(parents=True, exist_ok=True)
        access_handler = RotatingFileHandler(
            access_log_path, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
        )
        access_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        access_logger.addHandler(access_handler)
        access_logger.propagate = False

    @app.after_request
    def log_and_control_cache(response):
        if not app.config["TESTING"]:
            access_logger.info("%s %s %s", request.method, request.path, response.status_code)
        if response.mimetype == "text/html":
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify(error="not_found", path=request.path), 404

    with app.app_context():
        db.create_all()
        from .seed import seed_database

        seed_database()

    return app
