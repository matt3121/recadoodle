from __future__ import annotations

from datetime import UTC, datetime, timedelta
from time import monotonic

from flask import Flask, jsonify, render_template
from sqlalchemy.exc import SQLAlchemyError

from ..auth import GAME_VERSION
from ..extensions import db
from ..models import Account, Club, PlayerEvent, Presence, Room, RoomProfile


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _public_stats() -> dict:
    now = datetime.now(UTC)
    active_since = now - timedelta(minutes=5)
    player_count = db.session.scalar(
        db.select(db.func.count()).select_from(Account).where(Account.id != 1)
    ) or 0
    room_count = db.session.scalar(db.select(db.func.count()).select_from(Room)) or 0
    club_count = db.session.scalar(db.select(db.func.count()).select_from(Club)) or 0
    event_count = db.session.scalar(
        db.select(db.func.count()).select_from(PlayerEvent).where(PlayerEvent.end_at >= now)
    ) or 0
    online_count = db.session.scalar(
        db.select(db.func.count()).select_from(Presence).where(Presence.updated_at >= active_since)
    ) or 0
    recent_room_rows = db.session.execute(
        db.select(Room, RoomProfile.created_at)
        .join(RoomProfile, RoomProfile.room_id == Room.id)
        .order_by(RoomProfile.created_at.desc(), Room.id.desc())
        .limit(6)
    ).all()
    upcoming_events = db.session.scalars(
        db.select(PlayerEvent)
        .where(PlayerEvent.end_at >= now)
        .order_by(PlayerEvent.start_at, PlayerEvent.id)
        .limit(6)
    ).all()
    return {
        "players": int(player_count),
        "rooms": int(room_count),
        "clubs": int(club_count),
        "onlineNow": int(online_count),
        "upcomingEvents": int(event_count),
        "recentRooms": [
            {
                "id": room.id,
                "name": room.name,
                "description": room.description,
                "maxPlayers": room.max_players,
                "createdAt": _iso(created_at),
            }
            for room, created_at in recent_room_rows
        ],
        "events": [
            {
                "id": event.id,
                "name": event.name,
                "description": event.description,
                "roomId": event.room_id,
                "startAt": _iso(event.start_at),
                "endAt": _iso(event.end_at),
                "capacity": event.capacity,
            }
            for event in upcoming_events
        ],
    }


def register_dashboard_routes(app: Flask) -> None:
    @app.get("/api/server-stats")
    def server_stats():
        started_at = app.extensions["recadoodle_server_started_at"]
        server_version = app.extensions["recadoodle_server_version"]
        try:
            stats = _public_stats()
        except SQLAlchemyError:
            db.session.rollback()
            response = jsonify(
                name="Recadoodle",
                status="degraded",
                generatedAt=_iso(datetime.now(UTC)),
                uptimeSeconds=max(0, int(monotonic() - started_at)),
                version=server_version,
                gameVersion=GAME_VERSION,
                stats=None,
            )
            response.status_code = 503
            response.headers["Retry-After"] = "30"
        else:
            response = jsonify(
                name="Recadoodle",
                status="online",
                generatedAt=_iso(datetime.now(UTC)),
                uptimeSeconds=max(0, int(monotonic() - started_at)),
                version=server_version,
                gameVersion=GAME_VERSION,
                stats=stats,
            )
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    @app.get("/status")
    def status_page():
        return render_template(
            "status.html",
            game_version=GAME_VERSION,
            server_version=app.extensions["recadoodle_server_version"],
        )
