import json
import secrets
from pathlib import Path

from werkzeug.security import generate_password_hash

from .extensions import db
from .models import Account, Room

ROOM_DATA_PATH = Path(__file__).with_name("data") / "rooms.json"
BUILTIN_ROOMS = json.loads(ROOM_DATA_PATH.read_text(encoding="utf-8-sig"))


def seed_database() -> None:
    if db.session.get(Account, 1) is None:
        db.session.add(
            Account(
                id=1,
                username="Coach",
                display_name="Coach",
                password_hash=generate_password_hash(secrets.token_urlsafe(64)),
                is_developer=True,
                is_moderator=True,
            )
        )
    for source in BUILTIN_ROOMS:
        subrooms = source.get("SubRooms") or []
        if not subrooms:
            continue
        room_id = int(source["RoomId"])
        name = str(source["Name"])
        description = str(source.get("Description", ""))
        scene = str(subrooms[0]["UnitySceneId"])
        capacity = int(source.get("MaxPlayers") or subrooms[0].get("MaxPlayers") or 40)
        room = db.session.get(Room, room_id)
        if room is None:
            room = Room(
                id=room_id,
                name=name,
                description=description,
                scene=scene,
                max_players=capacity,
            )
            db.session.add(room)
        else:
            room.name = name
            room.description = description
            room.scene = scene
            room.max_players = capacity
    db.session.commit()
