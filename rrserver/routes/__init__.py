"""HTTP route registration grouped by responsibility."""

from __future__ import annotations

from flask import Flask

from .authentication import register_authentication_routes
from .protocol import register_protocol_routes
from .readiness import register_readiness_routes
from .server_info import register_server_info_routes


def register_routes(app: Flask) -> None:
    """Register the protocol-compatible API endpoints."""

    register_authentication_routes(app)
    register_protocol_routes(app)
    register_readiness_routes(app)
    register_server_info_routes(app)
