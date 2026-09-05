from importlib.metadata import PackageNotFoundError, version
from time import monotonic

from flask import Flask, jsonify

from ..auth import GAME_VERSION


def register_server_info_routes(app: Flask) -> None:
    started_at = monotonic()
    try:
        server_version = version("recadoodle")
    except PackageNotFoundError:
        server_version = "unknown"

    @app.get("/api/server-info")
    def server_info():
        response = jsonify(
            name="Recadoodle",
            version=server_version,
            gameVersion=GAME_VERSION,
            uptimeSeconds=max(0, int(monotonic() - started_at)),
        )
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response
