import io
from urllib.parse import urlparse

import jwt
import pytest

from rrserver import create_app
from rrserver.extensions import db
from rrserver.models import Account
from rrserver.notifications import notification_frame


@pytest.fixture()
def app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.sqlite3'}",
            "JWT_SECRET": "test-secret-longer-than-thirty-two-bytes",
            "RECNET_DOMAIN": "play.example.test",
            "SINGLE_HOST_MODE": False,
            "ALLOW_PASSWORDLESS_ACCOUNTS": True,
            "CREATE_DEVELOPER_ACCOUNTS_ON_LOGIN": False,
            "RATE_LIMIT_ENABLED": False,
        }
    )


@pytest.fixture()
def client(app):
    return app.test_client()


def create_player(client, password="correct horse battery staple"):
    response = client.post(
        "/connect/token",
        data={"grant_type": "create_account", "password": password, "ver": "20230414"},
    )
    assert response.status_code == 200
    return response.get_json()


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_full_orientation_is_enabled(client):
    config = {entry["Key"]: entry["Value"] for entry in client.get("/api/gameconfigs/v1/all").get_json()}
    assert config["Growth.QuickOrientationEnabled"] == "false"
    assert config["Lifecycle.NoOrientation.Platforms"] == ""


def test_live_notification_frame_matches_signalr_shape():
    frame = notification_frame(31, {"Id": 4, "Message": "Gift", "Empty": None})
    assert frame.endswith("\x1e")
    invocation = __import__("json").loads(frame[:-1])
    assert invocation["target"] == "Notification"
    payload = __import__("json").loads(invocation["arguments"][0])
    assert payload == {"Id": "31", "Msg": {"Id": 4, "Message": "Gift"}}


def test_discovery_has_expected_service_hosts(client):
    response = client.get("/")
    endpoints = response.get_json()
    assert urlparse(endpoints["Auth"]).hostname == "auth.play.example.test"
    assert urlparse(endpoints["Matchmaking"]).hostname == "match.play.example.test"
    assert endpoints["Moderation"] == "https://api.play.example.test"




def test_explicit_discovery_endpoint_is_json(client):
    response = client.get("/api/discovery", headers={"Accept": "text/html"})
    assert response.is_json
    assert response.get_json()["Auth"] == "https://auth.play.example.test"








def test_2023_startup_catalogs_are_published(client):
    api_config = client.get("/api/config/v2").get_json()
    assert len(api_config["LevelProgressionMaps"]) > 50
    assert api_config["ShareBaseUrl"] == "https://play.example.test/{0}"

    game_configs = client.get("/api/gameconfigs/v1/all").get_json()
    assert isinstance(game_configs, list)
    assert len(game_configs) > 400

    assert client.get("/config/RRPlusConfig_v3.json").status_code == 200
    assert client.get("/config/RRPlusConfig_v3").status_code == 200
    assert client.get("/config/not-published").status_code == 404


def test_2023_post_login_compatibility_responses(client):
    default_items = client.get("/api/avatar/v1/defaultunlocked").get_json()
    assert len(default_items) >= 3_061
    assert "AvatarItemDesc" in default_items[0]

    v4_items = client.get("/api/avatar/v4/items").get_json()
    assert len(v4_items) == len(default_items)
    assert set(v4_items[0]) == {
        "avatarItemId",
        "avatarItemDesc",
        "friendlyName",
        "tooltip",
        "tagList",
        "avatarItemType",
        "rarity",
        "isBaseAvatarItem",
    }

    requested_desc = default_items[100]["AvatarItemDesc"]
    locked_items = client.post(
        "/api/avatar/v1/lockeditems/bulk",
        json={"AvatarItemDescriptions": [requested_desc, "not-a-real-item"]},
    ).get_json()
    assert [item["AvatarItemDesc"] for item in locked_items] == [requested_desc]

    block = client.get("/api/PlayerReporting/v1/moderationBlockDetails").get_json()
    assert block["ReportCategory"] == -1
    assert block["IsBan"] is False
    assert block["Message"] is None
    assert client.get("/api/customAvatarItems/v1/isCreationAllowedForAccount").get_json() == {
        "success": True,
        "value": None,
    }
    assert client.get("/econ/customAvatarItems/v1/owned").get_json() == {
        "Results": [],
        "TotalResults": 0,
    }

    objective_progress = client.get("/api/objectives/v1/myprogress").get_json()
    assert objective_progress["Objectives"][0]["Progress"] == 0
    assert objective_progress["ObjectiveGroups"][0]["IsCompleted"] is False

    base_items = client.get("/api/avatar/v1/defaultbaseavataritems").get_json()
    assert len(base_items) >= 2
    assert base_items[0]["IsBaseAvatarItem"] is True

    equipment = client.get("/api/equipment/v2/getUnlocked").get_json()
    assert len(equipment) > 150
    assert {"ModificationGuid", "PrefabName", "Favorited"} <= set(equipment[0])

    consumables = client.get("/api/consumables/v2/getUnlocked").get_json()
    assert len(consumables) > 30
    assert consumables[0]["Count"] == 999

    storefront = client.get("/api/storefronts/v3/giftdropstore/3").get_json()
    assert len(storefront["StoreItems"]) > 1_000
    assert client.get("/api/storefronts/v3/giftdropstore/not-real").status_code == 404


def test_avatar_v2_requires_auth_and_returns_populated_default(client):
    assert client.get("/api/avatar/v2").status_code == 401

    tokens = create_player(client)
    response = client.get("/api/avatar/v2", headers=bearer(tokens["access_token"]))
    assert response.status_code == 200
    avatar = response.get_json()
    assert ";" in avatar["OutfitSelections"]
    assert "eyeId" in avatar["FaceFeatures"]
    assert avatar["SkinColor"]
    assert avatar["HairColor"]


def test_room_player_data_uses_empty_save_blob(client):
    assert client.get("/rooms/13/playerdata/me").get_json() == {"Data": ""}


def test_room_and_post_login_empty_data_have_2023_wire_shapes(client):
    room = client.get("/rooms/13").get_json()
    assert room["FriendlyName"] == "Orientation"
    assert room["CurrentSnapshotId"] is None
    assert room["SubRooms"][0]["CurrentSave"] is None

    tokens = create_player(client)
    headers = bearer(tokens["access_token"])
    assert client.get("/api/avatar/v3/saved", headers=headers).get_json() == []
    assert client.get("/api/images/v2/named").get_json() == []
    assert client.get("/api/messages/v2/get").status_code == 401
    assert client.get("/api/quickPlay/v1/getandclear").get_json() == {
        "RoomName": None,
        "ActionCode": None,
        "TargetPlayerId": None,
    }
    assert client.put("/player/photonregionpings").status_code == 200
    assert client.put("/player/statusvisibility").status_code == 200


def test_2023_progression_reputation_and_realtime_bootstrap(client):
    reputation = client.get("/api/playerReputation/v2/bulk?id=7&id=11").get_json()
    assert [item["AccountId"] for item in reputation] == [7, 11]
    assert reputation[0]["CheerCredit"] == 20

    progression = client.get("/api/players/v2/progression/bulk?id=7,11").get_json()
    assert progression == [
        {"PlayerId": 7, "Level": 1, "XP": 0},
        {"PlayerId": 11, "Level": 1, "XP": 0},
    ]

    negotiate = client.post("/hub/v1/negotiate?negotiateVersion=1").get_json()
    assert negotiate["negotiateVersion"] == 1
    assert negotiate["connectionId"] == negotiate["connectionToken"]
    assert negotiate["availableTransports"][0]["transport"] == "WebSockets"

    assert client.post("/api/gamesight/event").status_code == 200
    assert client.post("/data/event").get_json() == {}
    assert client.post("/data/heartbeat").get_json() == {}
    assert client.post("/pageview/consume").get_json() == {
        "FreshnessSeconds": 0.0,
        "Url": "",
    }
    assert client.get("/api/relationships/v2/get").status_code == 401


def test_avatar_and_saved_outfits_are_persistent(client):
    tokens = create_player(client)
    headers = bearer(tokens["access_token"])
    avatar = {"OutfitSelections": "saved;avatar", "SkinColor": "#123456"}
    assert client.post("/api/avatar/v2/set", headers=headers, json=avatar).get_json() == avatar
    assert client.get("/api/avatar/v2", headers=headers).get_json() == avatar

    outfit = {"Slot": 2, "PreviewImageName": "look.jpg", "OutfitSelections": "a;b"}
    assert (
        client.post("/api/avatar/v3/saved/set", headers=headers, json=outfit).get_json()
        == outfit
    )
    assert client.get("/api/avatar/v3/saved", headers=headers).get_json() == [outfit]


def test_friend_requests_and_room_interactions_are_persistent(client):
    first = create_player(client)
    second = create_player(client)
    first_headers = bearer(first["access_token"])
    second_headers = bearer(second["access_token"])
    first_id = client.get("/account/me", headers=first_headers).get_json()["accountId"]
    second_id = client.get("/account/me", headers=second_headers).get_json()["accountId"]

    sent = client.post(
        f"/api/relationships/v2/sendfriendrequest?id={second_id}", headers=first_headers
    ).get_json()
    assert sent["RelationshipType"] == 1
    received = client.get("/api/relationships/v2/get", headers=second_headers).get_json()
    assert received == [
        {
            "PlayerID": first_id,
            "RelationshipType": 2,
            "Favorited": 0,
            "Ignored": 0,
            "Muted": 0,
        }
    ]
    accepted = client.post(
        f"/api/relationships/v2/acceptfriendrequest?id={first_id}", headers=second_headers
    ).get_json()
    assert accepted["RelationshipType"] == 3

    interaction = client.put(
        "/rooms/2/interactionby/me/favorite", headers=first_headers
    ).get_json()
    assert interaction["Favorited"] is True
    assert client.get("/rooms/favoritedby/me", headers=first_headers).get_json()[0]["RoomId"] == 2

    client.post("/matchmake/room/3", headers=first_headers, data={"JoinMode": "0"})
    visited_ids = {
        room["RoomId"]
        for room in client.get("/rooms/visitedby/me", headers=first_headers).get_json()
    }
    assert visited_ids == {2, 3}


def test_friend_presence_follow_and_persistent_room_invites(client):
    first = create_player(client)
    second = create_player(client)
    first_headers = bearer(first["access_token"])
    second_headers = bearer(second["access_token"])
    first_id = client.get("/account/me", headers=first_headers).get_json()["accountId"]
    second_id = client.get("/account/me", headers=second_headers).get_json()["accountId"]
    client.post(f"/api/relationships/v2/addfriend?id={second_id}", headers=first_headers)

    entered = client.post("/matchmake/room/2", headers=first_headers).get_json()["roomInstance"]
    online = client.post(
        "/api/messages/v1/friendOnlineStatus", headers=second_headers
    ).get_json()
    assert online == {"success": True, "value": {"FriendsOnlineCount": 1}}

    followed = client.post(
        f"/matchmake/player/{first_id}", headers=second_headers
    ).get_json()
    assert followed["errorCode"] == 0
    assert followed["roomInstance"]["roomInstanceId"] == entered["roomInstanceId"]

    client.post("/goto/none", headers=second_headers)
    invite = client.post(
        "/invite",
        headers=first_headers,
        data={"playerId": second_id, "roomInstanceId": entered["roomInstanceId"]},
    ).get_json()
    assert invite["RoomId"] == 2
    inbox = client.get("/api/messages/v2/get", headers=second_headers).get_json()
    assert inbox[0]["Type"] == 6
    assert str(invite["RoomInviteId"]) in inbox[0]["Data"]

    accepted = client.post(
        f"/matchmake/invite/{invite['RoomInviteId']}", headers=second_headers
    ).get_json()
    assert accepted["errorCode"] == 0
    assert accepted["roomInstance"]["roomInstanceId"] == entered["roomInstanceId"]

    client.post(
        "/api/messages/v3/delete",
        headers=second_headers,
        json={"MessageIds": [inbox[0]["Id"]]},
    )
    assert client.get("/api/messages/v2/get", headers=second_headers).get_json() == []


def test_profile_support_endpoints_and_username_change(client):
    first = create_player(client)
    second = create_player(client)
    first_headers = bearer(first["access_token"])
    first_id = client.get("/account/me", headers=first_headers).get_json()["accountId"]
    second_name = client.get(
        "/account/me", headers=bearer(second["access_token"])
    ).get_json()["username"]

    changed = client.put(
        "/account/me/username", headers=first_headers, data={"username": "NewPlayer123"}
    ).get_json()
    assert changed["success"] is True
    assert changed["value"]["username"] == "NewPlayer123"
    duplicate = client.put(
        "/account/me/username", headers=first_headers, data={"username": second_name}
    ).get_json()
    assert duplicate == {
        "success": False,
        "error": "That username is already taken.",
        "value": "",
    }

    assert client.get(f"/accountprivacysettings/{first_id}").get_json() == {
        "accountId": first_id,
        "isRecentHistoryVisible": True,
    }
    assert client.get(f"/subscription/details/{first_id}").get_json() == {
        "accountId": first_id,
        "clubId": 0,
        "subscriberCount": 0,
    }
    assert client.get(f"/subscription/subscriberCount/{first_id}").get_json() == 0
    assert client.get("/subscription/details/rrplus").get_json() == {}
    assert client.get("/subscription/mine/member").get_json() == []
    assert client.get("/club/mine/created", headers=first_headers).get_json() == []
    assert client.get(f"/showcase/{first_id}").get_json() == []
    assert client.get(f"/api/customAvatarItems/v2/fromCreator/{first_id}").get_json() == {
        "Results": [],
        "TotalResults": 0,
    }


def test_discovery_events_and_notification_panels_have_shapes(client):
    filters = client.get("/api/rooms/v1/filters").get_json()
    assert "recroomoriginal" in filters["PinnedFilters"]
    assert filters["TrendingFilters"]

    event_filters = client.get("/api/playerevents/v1/tagfilters").get_json()
    assert "meetup" in event_filters["PinnedFilters"]
    assert event_filters["TrendingFilters"] is None
    assert client.get("/api/playerevents/v1/searchlive").get_json() == []
    assert client.get("/api/progressionEvents/active").get_json() == []
    assert client.get("/api/customAvatarItems/v1/featured").get_json() == {
        "Results": [],
        "TotalResults": 0,
    }

    categories = client.get("/config/categories").get_json()
    assert categories["TotalResults"] == len(categories["Results"]) == 1
    assert client.get("/club/categoryTags").get_json()[0] == "Social"
    assert client.get("/club/search").get_json() == {
        "Clubs": [],
        "ContinuationToken": None,
        "TotalClubs": 0,
    }
    assert client.get("/rooms/carousel/rising").get_json() == {
        "Results": [],
        "TotalResults": 0,
    }

    tokens = create_player(client)
    headers = bearer(tokens["access_token"])
    assert client.get("/preferences", headers=headers).get_json() == {"MutedCategories": []}
    assert client.get("/player/avoidjuniors", headers=headers).get_json() is False
    assert (
        client.put(
            "/player/avoidjuniors", headers=headers, data={"avoidJuniors": "True"}
        ).get_json()
        is True
    )
    assert client.get("/player/avoidjuniors", headers=headers).get_json() is True
    assert client.get("/api/images/v5/player/1").get_json() == []
    assert client.get("/api/messages/v1/favoriteFriendOnlineStatus").get_json() == []


def test_clubs_are_persistent_searchable_and_can_be_home(client):
    tokens = create_player(client)
    headers = bearer(tokens["access_token"])
    account_id = client.get("/account/me", headers=headers).get_json()["accountId"]
    created = client.post(
        "/club/create",
        headers=headers,
        data={"name": "Recadoodle Makers", "description": "Build together", "category": "Creative"},
    )
    assert created.status_code == 200
    details = created.get_json()["value"]
    club_id = details["ClubId"]
    assert details["Club"]["MemberCount"] == 1
    assert details["MyMembershipType"] == 100

    assert client.get("/club/mine/created", headers=headers).get_json()[0]["ClubId"] == club_id
    assert client.get("/club/mine/member", headers=headers).get_json()[0]["ClubId"] == club_id
    assert client.get(f"/club/account/{account_id}/created").get_json()[0]["ClubId"] == club_id
    search = client.get("/club/search?category=Creative&query=makers").get_json()
    assert search["TotalClubs"] == 1
    assert search["Clubs"][0]["Name"] == "Recadoodle Makers"

    home = client.put("/club/home/me", headers=headers, data={"clubId": club_id}).get_json()
    assert home["success"] is True
    assert client.get("/club/home/me", headers=headers).get_json()["ClubId"] == club_id
    assert client.delete("/club/home/me", headers=headers).get_json()["value"] is None
    assert client.get("/club/home/me", headers=headers).status_code == 404


def test_single_host_discovery(app):
    app.config["SINGLE_HOST_MODE"] = True
    endpoints = app.test_client().get("/").get_json()
    assert set(endpoints.values()) == {"https://play.example.test"}


def test_create_account_token_and_profile(client):
    tokens = create_player(client)
    payload = jwt.decode(
        tokens["access_token"], "test-secret-longer-than-thirty-two-bytes", algorithms=["HS256"]
    )
    assert payload["rn.ver"] == "20230414"
    assert "gameClient" in payload["role"]
    assert "developer" not in payload["role"]

    me = client.get("/account/me", headers=bearer(tokens["access_token"]))
    assert me.status_code == 200
    assert me.get_json()["username"].startswith("Player")


def test_create_account_can_be_promoted_to_developer_on_login(client, app):
    app.config["CREATE_DEVELOPER_ACCOUNTS_ON_LOGIN"] = True
    tokens = create_player(client, password="")
    payload = jwt.decode(
        tokens["access_token"], "test-secret-longer-than-thirty-two-bytes", algorithms=["HS256"]
    )
    profile = client.get("/account/me", headers=bearer(tokens["access_token"])).get_json()

    assert "developer" in payload["role"]
    assert "moderator" in payload["role"]
    with app.app_context():
        account = db.session.get(Account, profile["accountId"])
        assert account.is_developer is True
        assert account.is_moderator is True


def test_password_login_refresh_and_rotation(client):
    tokens = create_player(client)
    profile = client.get("/account/me", headers=bearer(tokens["access_token"])).get_json()
    login = client.post(
        "/connect/token",
        data={
            "grant_type": "password",
            "username": profile["username"],
            "password": "correct horse battery staple",
        },
    )
    assert login.status_code == 200

    refreshed = client.post(
        "/connect/token",
        data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]},
    )
    assert refreshed.status_code == 200
    reused = client.post(
        "/connect/token",
        data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]},
    )
    assert reused.status_code == 400


def test_passwordless_created_account_can_resume_with_empty_password(client):
    tokens = create_player(client, password="")
    profile = client.get("/account/me", headers=bearer(tokens["access_token"])).get_json()

    resumed = client.post(
        "/connect/token",
        data={
            "grant_type": "password",
            "account_id": str(profile["accountId"]),
            "password": "",
        },
    )

    assert resumed.status_code == 200
    assert "access_token" in resumed.get_json()


def test_matchmaking_updates_presence(client):
    tokens = create_player(client)
    headers = bearer(tokens["access_token"])
    matched = client.post("/matchmake/room/2", headers=headers, data={"JoinMode": "0"})
    body = matched.get_json()
    assert body["errorCode"] == 0
    assert body["roomInstance"]["roomId"] == 2
    assert body["roomInstance"]["location"] == "cbad71af-0831-44d8-b8ef-69edafa841f6"

    player_id = client.get("/account/me", headers=headers).get_json()["accountId"]
    presence = client.get(f"/player?id={player_id}").get_json()[0]
    assert presence["isOnline"] is True
    assert presence["roomInstance"]["roomId"] == 2

    photon = client.get("/photon_access_token", headers=headers)
    assert photon.status_code == 200
    assert photon.get_json()["RoomInstanceId"] == body["roomInstance"]["roomInstanceId"]
    assert photon.get_json()["PhotonAccessToken"] == ""
    assert any(
        item["Permission"] == "CAN_SPAWN_INVENTIONS"
        for item in photon.get_json()["Permissions"]
    )
    assert client.post("/roominstance/5/reportjoinresult").status_code == 200


def test_developer_gets_global_maker_pen_permission(client, app):
    tokens = create_player(client)
    profile = client.get("/account/me", headers=bearer(tokens["access_token"])).get_json()
    with app.app_context():
        from rrserver.extensions import db
        from rrserver.models import Account

        account = db.session.get(Account, profile["accountId"])
        account.is_developer = True
        db.session.commit()

    permissions = client.get(
        "/photon_access_token", headers=bearer(tokens["access_token"])
    ).get_json()["Permissions"]
    assert {
        "Override": True,
        "Permission": "CAN_USE_MAKER_PEN",
        "Role": 0,
        "Type": 0,
        "Value": "True",
    } in permissions

    assert (
        client.post(
            "/api/rooms/v1/verifyRole",
            headers=bearer(tokens["access_token"]),
            data={"roomId": "1", "role": "255", "context": "MakerPen"},
        ).get_json()
        is True
    )
    assert client.get("/api/CircuitChipLists/Favorites").get_json() == []
    assert client.get("/api/inventions/v2/mine").get_json() == []


def test_maker_pen_role_gate_rejects_unauthenticated_and_unknown_rooms(client):
    assert (
        client.post(
            "/api/rooms/v1/verifyRole",
            data={"roomId": "1", "role": "255", "context": "MakerPen"},
        ).get_json()
        is False
    )
    tokens = create_player(client)
    assert (
        client.post(
            "/api/rooms/v1/verifyRole?roomId=99999&role=0",
            headers=bearer(tokens["access_token"]),
        ).get_json()
        is False
    )


def test_creation_support_endpoints_use_builtin_shapes(client):
    assert client.get("/api/roomkeys/v1/room?roomId=1").get_json() == []
    assert client.get("/api/keepsakes/rooms/1").get_json() == []
    assert client.get("/api/keepsakes/globalconfig").get_json() == {}
    assert client.get("/api/keepsakes/categories").get_json() == {
        "Results": [],
        "TotalResults": 0,
    }
    assert client.get("/api/inventions/v2/search?skip=0&take=100").get_json() == []
    assert client.get("/api/inventions/v1/featured").get_json() == []
    assert client.get("/api/inventions/v1/tagfilters").get_json() == {
        "PinnedFilters": [],
        "PopularFilters": [],
        "TrendingFilters": None,
    }


def test_dorm_uses_the_2023_scene_identifier(client):
    tokens = create_player(client)
    matched = client.post(
        "/matchmake/room/DormRoom", headers=bearer(tokens["access_token"]), data={"JoinMode": "1"}
    ).get_json()
    assert matched["errorCode"] == 0
    assert matched["roomInstance"]["location"] == "76d98498-60a1-430c-ab76-b54a29b7a163"
    assert matched["roomInstance"]["isPrivate"] is True
    assert matched["roomInstance"]["roomInstanceType"] == 1


def test_each_account_gets_a_stable_personal_dorm(client):
    first = create_player(client)
    second = create_player(client)
    first_headers = bearer(first["access_token"])
    second_headers = bearer(second["access_token"])

    first_dorm = client.get("/dormroom/me", headers=first_headers).get_json()
    second_dorm = client.get("/dormroom/me", headers=second_headers).get_json()
    assert first_dorm != second_dorm
    assert client.get("/dormroom/me", headers=first_headers).get_json() == first_dorm

    first_room = client.get(f"/rooms/{first_dorm}").get_json()
    second_room = client.get(f"/rooms/{second_dorm}").get_json()
    assert first_room["Name"] == second_room["Name"] == "DormRoom"
    assert first_room["CreatorAccountId"] != second_room["CreatorAccountId"]
    assert first_room["SubRooms"][0]["RoomId"] == first_dorm


def test_builtin_room_feeds_and_thumbnails_are_available(client):
    hot = client.get("/rooms/hot?tag=rro&take=100").get_json()
    assert hot["TotalResults"] >= 40
    assert any(room["Name"] == "RecCenter" for room in hot["Results"])
    assert all(room["IsDorm"] is False for room in hot["Results"])
    assert client.get("/rooms/curated_playlists").get_json() == []


def test_magic_door_resolves_to_a_playable_room(client):
    room = client.get("/rooms/magic_door")
    assert room.status_code == 200
    assert room.get_json()["SubRooms"][0]["UnitySceneId"]


def test_every_archived_storefront_avatar_item_is_unlocked(client):
    unlocked = client.get("/api/avatar/v1/defaultunlocked").get_json()
    descriptions = {item["AvatarItemDesc"] for item in unlocked}
    assert "3044adce-90c0-4f66-81f5-39c4fca86fdf,Uz2hrptCa0erjqyPoiZxew,_Yq00H-NWUyQNvGxRunHbg," in descriptions

    thumbnail = client.get("/RecCenter.jpg?sig=p1")
    assert thumbnail.status_code == 200
    assert thumbnail.mimetype == "image/jpeg"
    assert thumbnail.headers["Content-Signature"].startswith("key-id=KEY:RSA:p1.rec.net")


def test_builtin_room_catalog_is_imported(client, app):
    charades = client.get("/rooms/3").get_json()
    assert charades["Name"] == "3DCharades"
    assert charades["SubRooms"][0]["UnitySceneId"] == "a673712c-877f-4749-b69a-4a4c6310d545"

    with app.app_context():
        from rrserver.extensions import db
        from rrserver.models import Room

        assert db.session.scalar(db.select(db.func.count()).select_from(Room)) >= 45


def test_2023_version_gate_and_settings(client):
    assert client.get("/api/versioncheck/v4?v=20230414").get_json()["VersionStatus"] == 0
    assert client.get("/api/versioncheck/v4?v=20250718.01").get_json()["VersionStatus"] == 1
    tokens = create_player(client)
    response = client.get("/playersettings", headers=bearer(tokens["access_token"]))
    assert {item["Key"] for item in response.get_json()} >= {"AvoidJuniors", "PlayerSessionCount"}


def test_builtin_2023_compatibility_endpoints_have_json_shapes(client):
    assert client.get("/rooms").get_json() == {}
    assert client.get("/rooms?name=orientation").get_json()["RoomId"] == 13
    assert client.get("/config/LoadingScreenTipData").get_json()[0]["Title"]
    assert client.get("/api/challenge/v2/getCurrent").get_json()["Challenges"] == []
    assert client.get("/api/playerevents/v1/all").get_json() == {
        "Created": [],
        "Responses": [],
    }
    assert client.get("/api/communityboard/v2/current").get_json()[
        "CurrentAnnouncement"
    ]["Message"] == "Welcome to Recadoodle"
    assert client.get("/api/storefronts/v3/giftdropstore/2000").get_json() == {
        "StoreItems": [],
        "StorefrontType": 2000,
    }
    assert client.post("/api/PlayerReporting/v1/hile").get_json() is False


def test_custom_room_clone_edit_save_publish_and_ban_are_persistent(client):
    tokens = create_player(client)
    headers = bearer(tokens["access_token"])
    account_id = client.get("/account/me", headers=headers).get_json()["accountId"]

    cloned = client.post("/rooms/1/clone", headers=headers, data={"name": "MyCoolRoom"})
    assert cloned.status_code == 200
    room = cloned.get_json()["value"]
    assert room["Name"] == "MyCoolRoom"
    room_id = room["RoomId"]
    subroom_id = room["SubRooms"][0]["SubRoomId"]

    assert client.put(
        f"/rooms/{room_id}/description", headers=headers, data={"description": "A saved room"}
    ).get_json()["Success"]
    client.put(f"/rooms/{room_id}/accessibility", headers=headers, data={"accessibility": "1"})
    created_subroom = client.post(
        f"/rooms/{room_id}/subrooms", headers=headers, data={"name": "Basement"}
    ).get_json()["value"]
    assert [sub["Name"] for sub in created_subroom["SubRooms"]] == ["Home", "Basement"]

    saved = client.post(
        f"/rooms/{room_id}/subrooms/{subroom_id}/data",
        headers=headers,
        json={"SubRoomData": {"Filename": "room-data-key"}, "Description": "first save"},
    ).get_json()
    save_id = saved["value"]["subRoomDataSave"]["id"]
    client.post(
        f"/rooms/{room_id}/subrooms/{subroom_id}/publish_save",
        headers=headers,
        data={"subRoomDataSaveId": str(save_id)},
    )
    loaded = client.get(f"/rooms/{room_id}").get_json()
    assert loaded["Description"] == "A saved room"
    assert loaded["SubRooms"][0]["CurrentSave"]["DataBlob"] == "room-data-key"

    ban = client.post(
        f"/rooms/{room_id}/bans", headers=headers, data={"id": account_id, "banMask": 1}
    )
    assert ban.get_json()["success"]
    assert client.get(
        f"/rooms/{room_id}/bans/{account_id}/isBanned", headers=headers
    ).get_json()["Value"]


def test_progression_media_leaderboard_and_compatibility_batch(client):
    tokens = create_player(client)
    headers = bearer(tokens["access_token"])
    player_id = client.get("/account/me", headers=headers).get_json()["accountId"]

    assert client.post("/api/objectives/v1/updateobjective", json={}).get_json()["success"]
    assert client.post("/api/gamerewards/v1/request", json={}).get_json()["Rewards"] == []
    score = client.post(
        "/leaderboard/CheckAndSetStat",
        headers=headers,
        json={"LeaderboardName": "PaintballWins", "Score": 12},
    ).get_json()
    assert score["Score"] == 12
    rank = client.post(
        "/leaderboard/GetPlayerRank",
        headers=headers,
        json={"LeaderboardName": "PaintballWins"},
    ).get_json()
    assert rank == {"PlayerId": player_id, "Rank": 1, "Score": 12}

    uploaded = client.post(
        "/api/images/v4/uploadsaved",
        headers=headers,
        json={"ImageName": "photo-key", "RoomId": 2, "Caption": "Hello"},
    ).get_json()
    assert uploaded["ImageName"] == "photo-key"
    assert client.get(f"/api/images/v5/bulk?ids={uploaded['Id']}").get_json()[0]["Caption"] == "Hello"
    assert client.get("/api/roomconsumables/v1/roomConsumable/room/2").get_json()["Consumables"] == []
    assert client.get("/parentalcontrol/me").status_code == 200


def test_game_rewards_and_token_store_purchases_are_persistent(client):
    tokens = create_player(client)
    headers = bearer(tokens["access_token"])

    first_reward = client.post(
        "/api/gamerewards/v1/request",
        headers=headers,
        json={"GameSessionId": "completed-session-1"},
    ).get_json()
    assert first_reward == {
        "Balance": 10100,
        "Rewards": [{"Amount": 100, "CurrencyType": 2}],
        "Success": True,
    }
    repeated_reward = client.post(
        "/api/gamerewards/v1/request",
        headers=headers,
        json={"GameSessionId": "completed-session-1"},
    ).get_json()
    assert repeated_reward["Rewards"] == []
    assert repeated_reward["Balance"] == 10100

    purchase = client.post(
        "/api/storefronts/v3/purchase",
        headers=headers,
        json={"PurchasableItemId": 7, "ExpectedPrice": 3000},
    )
    assert purchase.status_code == 200
    receipt = purchase.get_json()
    assert receipt["Success"] is True
    assert receipt["Balance"] == 7100
    assert receipt["GiftDrop"]["FriendlyName"] == "Archer Quiver (Grey)"
    assert receipt["TransactionId"] == receipt["transactionId"]
    assert client.get("/api/storefronts/v4/balance/2", headers=headers).get_json() == {
        "Balance": 7100,
        "CurrencyType": 2,
    }

    duplicate = client.post(
        "/api/storefronts/v1/purchase",
        headers=headers,
        json={"PurchasableItemId": 7, "ExpectedPrice": 3000},
    )
    assert duplicate.status_code == 409
    assert duplicate.get_json()["Error"] == "You already own this item."


def test_game_rewards_respect_the_daily_limit(client):
    tokens = create_player(client)
    headers = bearer(tokens["access_token"])
    for session_number in range(10):
        response = client.post(
            "/api/gamerewards/v1/request",
            headers=headers,
            json={"GameSessionId": f"daily-session-{session_number}"},
        ).get_json()
        assert response["Rewards"] == [{"Amount": 100, "CurrencyType": 2}]

    capped = client.post(
        "/api/gamerewards/v1/request",
        headers=headers,
        json={"GameSessionId": "daily-session-capped"},
    ).get_json()
    assert capped["Rewards"] == []
    assert capped["Balance"] == 11000


def test_room_blob_storage_round_trip_and_subroom_history(client):
    tokens = create_player(client)
    headers = bearer(tokens["access_token"])
    uploaded = client.post(
        "/upload",
        headers=headers,
        data={"FileType": "1", "File": (io.BytesIO(b"maker-pen-room-data"), "room.bin")},
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    blob_name = uploaded.get_json()["filename"]
    downloaded = client.get(f"/room/{blob_name}")
    assert downloaded.data == b"maker-pen-room-data"
    assert downloaded.headers["X-Content-SHA256"]

    room = client.post("/rooms/1/clone", headers=headers, data={"name": "PersistentBuild"}).get_json()["value"]
    room_id = room["RoomId"]
    subroom_id = room["SubRooms"][0]["SubRoomId"]
    saved = client.post(
        f"/rooms/{room_id}/subrooms/{subroom_id}/data",
        headers=headers,
        json={"SubRoomData": {"Filename": blob_name}, "AutoPublish": True},
    ).get_json()["value"]["subRoomDataSave"]
    assert client.get(
        f"/rooms/{room_id}/subrooms/{subroom_id}/saves/{saved['id']}", headers=headers
    ).get_json()["dataBlob"] == blob_name
    cloned = client.post(
        f"/rooms/{room_id}/subrooms/{subroom_id}/clone", headers=headers
    ).get_json()["value"]
    assert len(cloned["SubRooms"]) == 2
    clone_id = cloned["SubRooms"][1]["SubRoomId"]
    assert client.delete(f"/rooms/{room_id}/subrooms/{clone_id}", headers=headers).get_json()["success"]


def test_room_settings_permissions_circuit_and_video_values_persist(client):
    tokens = create_player(client)
    headers = bearer(tokens["access_token"])
    room = client.post("/rooms/1/clone", headers=headers, data={"name": "ConfiguredRoom"}).get_json()["value"]
    room_id = room["RoomId"]
    subroom_id = room["SubRooms"][0]["SubRoomId"]

    client.put(f"/rooms/{room_id}/warning", headers=headers, data={"warningMask": 4, "customWarning": "Flashing lights"})
    client.put(f"/rooms/{room_id}/tags", headers=headers, data={"tag": ["game", "social"]})
    client.put(f"/rooms/{room_id}/restrictions", headers=headers, data={"supportsScreens": "False", "supportsWalkVR": "True"})
    client.put(f"/rooms/{room_id}/loadscreen", headers=headers, data={"imageName": "load-photo", "title": "Welcome"})
    configured = client.get(f"/rooms/{room_id}").get_json()
    assert configured["WarningMask"] == 4
    assert configured["Tags"] == [{"Tag": "game", "Type": 0}, {"Tag": "social", "Type": 0}]
    assert configured["SupportsScreens"] is False
    assert configured["LoadScreens"][0]["Title"] == "Welcome"

    permissions = [{"Permission": "CAN_USE_MAKER_PEN", "Role": 0, "Override": True, "Value": "True"}]
    assert client.put(
        f"/rooms/{room_id}/subrooms/{subroom_id}/permissions", headers=headers, json=permissions
    ).status_code == 200
    client.post(f"/matchmake/room/{room_id}", headers=headers)
    photon_permissions = client.get("/photon_access_token", headers=headers).get_json()["Permissions"]
    assert any(
        item["Permission"] == "CAN_USE_MAKER_PEN"
        and item["Role"] == 0
        and item["Value"] == "True"
        for item in photon_permissions
    )

    client.put(
        f"/api/rooms/v1/{room_id}/circuit-values",
        headers=headers,
        json={"Key": "scoreName", "Value": "orange team"},
    )
    assert client.get(
        f"/api/rooms/v1/{room_id}/circuit-values", headers=headers
    ).get_json()["scoreName"] == "orange team"
    client.put(
        f"/api/rooms/v1/{room_id}/remote-video-urls",
        headers=headers,
        json={"PlayerId": "screen1", "Url": "https://example.com/video.mp4"},
    )
    assert client.get(
        f"/api/rooms/v1/{room_id}/remote-video-urls", headers=headers
    ).get_json()["screen1"] == "https://example.com/video.mp4"


def test_events_club_membership_and_safe_purchase_flow(client):
    creator = create_player(client)
    guest = create_player(client)
    creator_headers = bearer(creator["access_token"])
    guest_headers = bearer(guest["access_token"])
    guest_id = client.get("/account/me", headers=guest_headers).get_json()["accountId"]

    event = client.post(
        "/api/playerevents/v2",
        headers=creator_headers,
        json={
            "RoomId": 2,
            "Name": "Recadoodle Meetup",
            "Description": "Play together",
            "StartTime": "2027-01-01T18:00:00Z",
            "EndTime": "2027-01-01T19:00:00Z",
            "Tags": [{"Tag": "meetup", "Type": 0}],
        },
    ).get_json()["PlayerEvent"]
    event_id = event["PlayerEventId"]
    assert client.get(f"/api/playerevents/v1/{event_id}").get_json()["Name"] == "Recadoodle Meetup"
    responded = client.post(
        "/api/playerevents/v1/respond",
        headers=guest_headers,
        json={"PlayerEventId": event_id, "Type": 0},
    ).get_json()
    assert responded["PlayerEvent"]["AttendeeCount"] == 2

    club = client.post("/club/create", headers=creator_headers, data={"name": "Builders"}).get_json()["value"]["Club"]
    club_id = club["ClubId"]
    invited = client.post(
        f"/club/{club_id}/members/invite",
        headers=creator_headers,
        json={"AccountIds": [guest_id]},
    ).get_json()
    assert invited["value"] == [guest_id]
    assert len(client.get(f"/club/{club_id}/members").get_json()) == 2
    assert client.post(f"/club/{club_id}/leave", headers=guest_headers).get_json()["success"]

    assert client.get("/purchase/v1/hasspentmoney").get_json() is False
    assert client.post("/purchase/v1/initiatepurchase", json={}).get_json()["transactionId"]
    assert client.get("/purchase/v1/cleanuppending").get_json() == []


def test_event_management_clubhouse_announcements_and_consumables(client):
    creator = create_player(client)
    headers = bearer(creator["access_token"])
    event = client.post(
        "/api/playerevents/v2",
        headers=headers,
        json={"RoomId": 2, "Name": "Original", "StartTime": "2027-02-01T18:00:00Z"},
    ).get_json()["PlayerEvent"]
    event_id = event["PlayerEventId"]
    edited = client.put(
        f"/api/playerevents/v2/{event_id}",
        headers=headers,
        json={"Name": "Edited Event", "Description": "Updated"},
    ).get_json()["PlayerEvent"]
    assert edited["Name"] == "Edited Event"

    club = client.post("/club/create", headers=headers, data={"name": "Event Hosts"}).get_json()["value"]["Club"]
    club_id = club["ClubId"]
    clubhouse = client.put(
        f"/club/{club_id}/clubhouse", headers=headers, data={"roomId": 2}
    ).get_json()["value"]["Club"]
    assert clubhouse["ClubhouseRoomId"] == 2
    announcement_id = client.post(
        f"/announcements/club/{club_id}",
        headers=headers,
        data={"title": "Tonight", "message": "Meet in the clubhouse"},
    ).get_json()["value"]
    announcement = client.get(f"/announcements/club/{club_id}").get_json()
    assert announcement["LastAnnouncementId"] == announcement_id

    consumables = client.get("/api/consumables/v2/getUnlocked", headers=headers).get_json()
    item = consumables[0]
    assert client.post(
        "/api/consumables/v1/consume",
        headers=headers,
        json={"Id": item["Ids"][0], "DeltaCount": 2},
    ).get_json()
    updated = client.get("/api/consumables/v2/getUnlocked", headers=headers).get_json()[0]
    assert updated["Count"] == item["Count"] - 2
    assert client.post(f"/api/playerevents/v2/delete/{event_id}", headers=headers).get_json()["Result"] == 0


def test_room_comments_party_and_instance_state_batch(client):
    tokens = create_player(client)
    headers = bearer(tokens["access_token"])

    assert client.get("/settings/partyinvite").status_code == 401
    assert client.get("/settings/partyinvite", headers=headers).get_json() == {
        "InviteLinkLifetimeInMinutes": 60
    }
    assert client.get("/thread/party?maxCount=1&mode=0", headers=headers).get_json() == {}

    created = client.post(
        "/comments/create/2",
        headers=headers,
        data={
            "message": "  Great room!  ",
            "subRoomId": "2",
            "style": "3",
            "positionX": "1.25",
            "positionY": "garbled",
        },
    ).get_json()
    assert created["Message"] == "Great room!"
    assert created["AccountId"] > 0
    assert created["PositionX"] == 1.25
    assert created["PositionY"] == 0
    assert created["Unread"] is True
    assert client.get("/comments/get/2?count=10&minId=-1").get_json()[0] == created
    assert client.get("/comments/get/2?subRoomId=999").get_json() == []
    assert client.post("/comments/create/2", data={"message": "no auth", "subRoomId": 2}).status_code == 401

    matched = client.post("/matchmake/room/2", headers=headers).get_json()
    instance_id = matched["roomInstance"]["roomInstanceId"]
    assert client.put(
        f"/roominstance/{instance_id}/inprogress",
        headers=headers,
        data={"inProgress": "True"},
    ).status_code == 200
    assert client.post(
        f"/roominstance/{instance_id}/markprivate", headers=headers
    ).status_code == 403


def test_persistent_chat_threads_messages_and_privacy(client):
    first = create_player(client)
    second = create_player(client)
    first_headers = bearer(first["access_token"])
    second_headers = bearer(second["access_token"])
    second_id = client.get("/account/me", headers=second_headers).get_json()["accountId"]

    opened = client.post(
        "/thread/withmembers",
        headers=first_headers,
        data={"ids": str(second_id), "messageCount": "50"},
    ).get_json()
    thread_id = opened["chatThreadId"]
    assert opened["messages"] == []
    assert sorted(opened["playerIds"]) == sorted(
        [client.get("/account/me", headers=first_headers).get_json()["accountId"], second_id]
    )

    envelope = '{"Type":0,"Version":1,"Data":"hello"}'
    sent = client.post(
        f"/thread/{thread_id}", headers=first_headers, data={"messageContents": envelope}
    ).get_json()
    assert sent["ChatResult"] == 0
    assert sent["ChatMessage"]["Contents"] == envelope
    assert client.get("/thread", headers=second_headers).get_json()[0]["latestMessage"][
        "contents"
    ] == envelope
    history = client.get(
        f"/thread/{thread_id}/message?MessageCount=16", headers=second_headers
    ).get_json()
    assert history[0]["senderPlayerId"] != second_id

    privacy = client.put(
        "/thread/chatPrivacySetting",
        headers=first_headers,
        data={"directMessagePrivacySetting": "Favorites"},
    ).get_json()
    assert privacy["directMessagePrivacySetting"] == 1
    assert privacy["groupChatPrivacySetting"] == 0
    assert client.get(
        "/thread/checkCanSendDirectMessageWithPrivacySetting?receivingPlayerId=1",
        headers=first_headers,
    ).get_json() == 0

    assert client.post(
        f"/thread/{thread_id}/rename", headers=first_headers, data={"name": "Builders"}
    ).get_json() == 0
    assert client.post(
        f"/thread/{thread_id}/favorite", headers=first_headers, data={"isFavorite": "True"}
    ).get_json() == 0
    message_id = history[0]["chatMessageId"]
    assert client.post(
        f"/thread/{thread_id}/message/{message_id}/read", headers=second_headers
    ).get_json() == 0
    assert client.delete(f"/thread/{thread_id}/leave", headers=second_headers).get_json() == 0






def test_equipment_catalog_carousel_and_test_management_batch(client):
    tokens = create_player(client)
    headers = bearer(tokens["access_token"])
    equipment = client.get("/api/equipment/v2/getUnlocked", headers=headers).get_json()
    item = equipment[0]
    item["Favorited"] = True
    assert client.post("/api/equipment/v1/update", headers=headers, json=[item]).status_code == 200
    updated = client.get("/api/equipment/v2/getUnlocked", headers=headers).get_json()
    assert updated[0]["ModificationGuid"] == item["ModificationGuid"]
    assert updated[0]["Favorited"] is True
    assert client.post("/api/equipment/v1/update", headers=headers, json={}).status_code == 400
    assert client.post("/api/equipment/v1/update", json=[]).status_code == 401

    catalog = client.get("/api/catalog/v1/all?onlyAvailableSkus=true").get_json()
    assert isinstance(catalog, list)
    assert catalog and "skuId" in catalog[0]
    carousel = client.get("/api/storefronts/v1/adcarouselitems").get_json()
    assert carousel[0]["AdCarouselItemId"] == 1
    assert client.get("/api/testcasemanagement/v1/testplans").get_json() == []
    assert client.get("/api/testcasemanagement/v1/testpasssummary").get_json() == []


def test_maker_pen_contest_skins_are_unlocked_without_duplicates(client):
    items = client.get("/api/equipment/v2/getUnlocked").get_json()
    pens = [item for item in items if item["PrefabName"] == "[MakerPen]"]
    assert len(pens) == 30
    assert len({item["ModificationGuid"] for item in pens}) == 30
    assert any(item["FriendlyName"] == "Maker Pen (Contest Stranded)" for item in pens)
    tokens = create_player(client)
    headers = bearer(tokens["access_token"])
    contest = next(item for item in pens if item["FriendlyName"] == "Maker Pen (Dragon)")
    assert client.post(
        "/api/equipment/v1/update", headers=headers,
        json=[{**contest, "Favorited": True}],
    ).status_code == 200
    refreshed = client.get("/api/equipment/v2/getUnlocked", headers=headers).get_json()
    assert next(item for item in refreshed if item["ModificationGuid"] == contest["ModificationGuid"])["Favorited"]
