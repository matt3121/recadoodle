"""Application-wide HTTP hardening and small dependency-free rate limits."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from flask import Flask, current_app, jsonify, request


def password_problem(password: str, *, allow_empty: bool = False) -> str | None:
    """Return a safe user-facing password validation error, if any."""

    if not password and allow_empty:
        return None
    minimum = int(current_app.config["MIN_PASSWORD_LENGTH"])
    if len(password) < minimum:
        return f"Password must be at least {minimum} characters long."
    if len(password) > 256:
        return "Password must be no more than 256 characters long."
    return None


class RequestLimiter:
    """Per-process fixed-window protection for authentication and uploads.

    Production deployments with multiple workers should additionally enforce limits at
    the reverse proxy. This local limiter still protects each worker from simple bursts.
    """

    def __init__(self) -> None:
        self._requests: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allowed(self, bucket: str, identity: str, limit: int, window: int) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - window
        key = (bucket, identity)
        with self._lock:
            attempts = self._requests[key]
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if len(attempts) >= limit:
                return False, max(1, int(window - (now - attempts[0])))
            attempts.append(now)
        return True, 0


def register_security(app: Flask) -> None:
    limiter = RequestLimiter()
    app.extensions["request_limiter"] = limiter

    @app.before_request
    def protect_sensitive_endpoints():
        if not app.config["RATE_LIMIT_ENABLED"] or request.method == "OPTIONS":
            return None

        rule = None
        if request.path == "/connect/token":
            rule = ("token", 30, 60)
        elif request.path == "/admin/login" and request.method == "POST":
            rule = ("admin-login", 10, 300)
        elif request.path in {"/upload", "/account/me/profilephoto"} and request.method == "POST":
            rule = ("upload", 20, 60)
        if rule is None:
            return None

        identity = request.remote_addr or "unknown"
        allowed, retry_after = limiter.allowed(rule[0], identity, rule[1], rule[2])
        if allowed:
            return None
        response = jsonify(error="rate_limited", retryAfter=retry_after)
        response.status_code = 429
        response.headers["Retry-After"] = str(retry_after)
        return response

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        if response.mimetype == "text/html":
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "form-action 'self'; frame-ancestors 'none'; base-uri 'self'",
            )
        if request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")

        origin = request.headers.get("Origin")
        allowed_origins = app.config["CORS_ALLOWED_ORIGINS"]
        if origin and origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers.setdefault(
                "Access-Control-Allow-Headers", "Authorization, Content-Type, X-Requested-With"
            )
            response.headers.setdefault(
                "Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS"
            )
        return response
