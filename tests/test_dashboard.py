from datetime import UTC, datetime, timedelta

from rrserver import create_app
from rrserver.extensions import db
from rrserver.models import Account, Club, PlayerEvent, Presence, Room, RoomProfile


def test_dashboard_stats_include_public_activity(tmp_path):
    app = create_app({
        "TESTING": True,
        "JWT_SECRET": "test-secret-longer-than-thirty-two-bytes",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'dashboard.sqlite3'}",
        "TRUSTED_HOSTS": None,
    })
    now = datetime.now(UTC)
    with app.app_context():
        account = Account(username="dashboard", display_name="Dashboard", password_hash="x")
        db.session.add(account)
        db.session.flush()
        room = Room(
            name="DashboardRoom",
            description="A public room",
            scene="MakerRoom",
            creator_account_id=account.id,
        )
        db.session.add(room)
        db.session.flush()
        db.session.add(RoomProfile(room_id=room.id, created_at=now))
        db.session.add(Presence(account_id=account.id, room_id=room.id, updated_at=now))
        db.session.add(Club(name="Dashboard Club", creator_account_id=account.id))
        db.session.add(PlayerEvent(
            creator_account_id=account.id,
            room_id=room.id,
            name="Dashboard Event",
            description="Starts soon",
            start_at=now + timedelta(hours=1),
            end_at=now + timedelta(hours=2),
            capacity=12,
        ))
        db.session.commit()

    response = app.test_client().get("/api/server-stats")
    body = response.get_json()
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store, max-age=0"
    assert body["name"] == "Recadoodle"
    assert body["status"] == "online"
    assert body["stats"]["players"] >= 1
    assert body["stats"]["onlineNow"] == 1
    assert body["stats"]["clubs"] >= 1
    assert body["stats"]["upcomingEvents"] == 1
    assert body["stats"]["recentRooms"][0]["name"] == "DashboardRoom"
    assert body["stats"]["events"][0]["name"] == "Dashboard Event"
    assert app.test_client().head("/api/server-stats").data == b""


def test_dashboard_page_has_live_sections(tmp_path):
    app = create_app({
        "TESTING": True,
        "JWT_SECRET": "test-secret-longer-than-thirty-two-bytes",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'page.sqlite3'}",
        "TRUSTED_HOSTS": None,
    })
    page = app.test_client().get("/status").get_data(as_text=True)
    assert "RecadoodleAPI" in page
    assert "Server dashboard" in page
    assert "Online now" in page
    assert "Recently created rooms" in page
    assert "Upcoming events" in page
    assert "/api/server-stats" in page
