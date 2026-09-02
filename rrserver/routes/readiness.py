from flask import Flask, jsonify
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db


def register_readiness_routes(app: Flask) -> None:
    @app.get("/readyz")
    def readiness():
        try:
            with db.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            response = jsonify(status="not_ready", checks={"database": "unavailable"})
            response.status_code = 503
            response.headers["Retry-After"] = "30"
        else:
            response = jsonify(status="ready", checks={"database": "ok"})
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response
