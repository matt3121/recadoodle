from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from time import monotonic

from flask import Flask, jsonify

from ..auth import GAME_VERSION


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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
            serverTimeUtc=_utc_now(),
            uptimeSeconds=max(0, int(monotonic() - started_at)),
        )
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response
