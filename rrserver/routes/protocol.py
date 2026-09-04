from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from flask import (
    Flask,
    current_app,
    jsonify,
    request,
    send_file,
)
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from ..auth import (
    GAME_VERSION,
    current_account,
    require_account,
)
from ..catalog import (
    AD_CAROUSEL_ITEMS,
    ALL_UNLOCKS,
    API_CONFIG_V2,
    BUILTIN_ROOMS_BY_ID,
    COMMUNITY_BOARD,
    DATA_DIR,
    DEFAULT_AVATAR,
    DEFAULT_BASE_AVATAR_ITEMS,
    DEFAULT_SETTINGS,
    FULL_AVATAR_ITEMS,
    GAME_CONFIGS_2023,
    LOADING_SCREEN_TIPS,
    MY_PROGRESS,
    PUBLISHED_CONFIGS,
    PURCHASABLE_CATALOG,
    ROOM_IMAGE_DIR,
    SERVICE_SUBDOMAINS,
    STORE_ITEMS_BY_ID,
    STOREFRONT_FILES,
    VOTE_TO_KICK_REASONS,
)
from ..extensions import db
from ..models import (
    Account,
    AvatarState,
    ChatMessage,
    ChatThread,
    ChatThreadMember,
    CircuitValue,
    Club,
    ClubAnnouncement,
    ClubMember,
    ConsumableBalance,
    EquipmentPreference,
    HomeClub,
    LeaderboardScore,
    OwnedStoreItem,
    PlayerEvent,
    PlayerEventResponse,
    PlayerImage,
    PlayerMessage,
    PlayerReport,
    PlayerSetting,
    Presence,
    ReceivedGift,
    Relationship,
    Room,
    RoomBan,
    RoomComment,
    RoomInstanceState,
    RoomInteraction,
    RoomInvite,
    RoomProfile,
    RoomRole,
    RoomSave,
    RoomSetting,
    SavedOutfit,
    StorePurchase,
    SubRoom,
    SubRoomPermission,
    TokenTransaction,
)


def _query_ids() -> list[int]:
    ids: list[int] = []
    for value in request.args.getlist("id"):
        ids.extend(int(item) for item in value.split(",") if item.strip().isdigit())
    return ids


def _avatar_item_v4(item: dict) -> dict:
    return {
        "avatarItemId": item.get("AvatarItemId", 0),
        "avatarItemDesc": item.get("AvatarItemDesc", ""),
        "friendlyName": item.get("FriendlyName", ""),
        "tooltip": item.get("Tooltip", ""),
        "tagList": item.get("TagList", ""),
        "avatarItemType": item.get("AvatarItemType", 0),
        "rarity": item.get("Rarity", 0),
        "isBaseAvatarItem": item.get("IsBaseAvatarItem") is True,
    }


def _default_reputation(account_id: int) -> dict:
    return {
        "AccountId": account_id,
        "IsCheerful": True,
        "Noteriety": 0,
        "SelectedCheer": 0,
        "CheerCredit": 20,
        "CheerGeneral": 0,
        "CheerHelpful": 0,
        "CheerCreative": 0,
        "CheerGreatHost": 0,
        "CheerSportsman": 0,
        "SubscriberCount": 0,
        "SubscribedCount": 0,
    }


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def account_dto(account: Account) -> dict:
    return {
        "accountId": account.id,
        "username": account.username,
        "displayName": account.display_name,
        "profileImage": account.profile_image,
        "bannerImage": "",
        "displayEmoji": "",
        "isJunior": account.is_junior,
        "platforms": account.platforms,
        "personalPronouns": account.personal_pronouns,
        "identityFlags": account.identity_flags,
        "createdAt": _iso(account.created_at),
    }


def self_account_dto(account: Account) -> dict:
    return {
        **account_dto(account),
        "email": account.email,
        "birthday": "1904-01-01T00:00:00.000Z",
        "availableUsernameChanges": 1,
    }


def _is_dorm(room: Room) -> bool:
    return room.id == 1 or room.name.startswith("DormRoom_")


def _personal_dorm_id(account_id: int) -> int:
    return 10_000_000 + account_id


def _get_or_create_personal_dorm(account: Account) -> Room:
    room_id = _personal_dorm_id(account.id)
    room = db.session.get(Room, room_id)
    if room is not None:
        return room

    template = db.session.get(Room, 1)
    room = Room(
        id=room_id,
        name=f"DormRoom_{account.id}",
        description=template.description,
        scene=template.scene,
        max_players=template.max_players,
        creator_account_id=account.id,
    )
    db.session.add(room)
    db.session.commit()
    return room


def room_dto(room: Room) -> dict:
    personal_dorm = room.name.startswith("DormRoom_")
    imported = BUILTIN_ROOMS_BY_ID.get(1 if personal_dorm else room.id)
    if imported is not None:
        result = copy.deepcopy(imported)
        if personal_dorm:
            result["RoomId"] = room.id
            result["Name"] = "DormRoom"
            result["FriendlyName"] = "Dorm Room"
            result["CreatorAccountId"] = room.creator_account_id
            result["Roles"] = [
                {
                    "AccountId": room.creator_account_id,
                    "Role": 255,
                    "LastChangedByAccountId": None,
                    "InvitedRole": 0,
                }
            ]
            for subroom in result.get("SubRooms", []):
                subroom["SubRoomId"] = room.id
                subroom["RoomId"] = room.id
                subroom["CreatorAccountId"] = room.creator_account_id
        result.setdefault("BoostCount", 0)
        result.setdefault("CurrentSnapshotId", None)
        result.setdefault("FriendlyName", result.get("Name", ""))
        result.setdefault("CCU", None)
        for subroom in result.get("SubRooms", []):


            subroom.setdefault("CurrentSave", None)
        return result
    profile = db.session.get(RoomProfile, room.id)
    settings = db.session.get(RoomSetting, room.id)
    subrooms = db.session.scalars(
        db.select(SubRoom).where(SubRoom.room_id == room.id).order_by(SubRoom.id)
    ).all()
    roles = db.session.scalars(db.select(RoomRole).where(RoomRole.room_id == room.id)).all()
    if not subrooms:
        subrooms = [
            SubRoom(
                id=room.id,
                room_id=room.id,
                name="Home",
                scene=room.scene,
                max_players=room.max_players,
            )
        ]

    def save_dto(save: RoomSave | None) -> dict | None:
        if save is None:
            return None
        return {
            "SubRoomDataSaveId": save.id,
            "SubRoomId": save.sub_room_id,
            "SavedByAccountId": save.saved_by_account_id,
            "SavedOnPlatform": 0,
            "SavedOnDeviceClass": 0,
            "Description": save.description,
            "CreatedAt": _iso(save.created_at),
            "UnityAssetId": save.unity_asset_id,
            "DataBlob": save.data,
        }

    return {
        "RoomId": room.id,
        "Name": room.name,
        "Description": room.description,
        "CreatorAccountId": room.creator_account_id,
        "ImageName": profile.image_name if profile else "",
        "FriendlyName": room.name,
        "State": 0,
        "Accessibility": profile.accessibility if profile else 0,
        "PublishState": profile.publish_state if profile else 0,
        "WarningMask": settings.warning_mask if settings else 0,
        "CustomWarning": settings.custom_warning or None if settings else None,
        "CloningAllowed": profile.cloning_allowed if profile else True,
        "CreatedAt": _iso(profile.created_at) if profile else _iso(datetime.now(UTC)),
        "PublishedAt": _iso(profile.published_at) if profile and profile.published_at else None,
        "IsDorm": _is_dorm(room),
        "IsRRO": False,
        "MaxPlayers": room.max_players,
        "SupportsScreens": json.loads(settings.restrictions_json).get("SupportsScreens", True) if settings else True,
        "SupportsWalkVR": json.loads(settings.restrictions_json).get("SupportsWalkVR", True) if settings else True,
        "SupportsTeleportVR": json.loads(settings.restrictions_json).get("SupportsTeleportVR", True) if settings else True,
        "SubRooms": [
            {
                "SubRoomId": subroom.id,
                "RoomId": room.id,
                "CreatorAccountId": room.creator_account_id,
                "UnitySceneId": subroom.scene,
                "Name": subroom.name,
                "MaxPlayers": subroom.max_players,
                "Accessibility": subroom.accessibility,
                "IsSandbox": True,
                "ShouldAutoStageSaves": True,
                "StagedSubRoomDataSaveId": subroom.staged_save_id,
                "CurrentSave": save_dto(
                    db.session.get(RoomSave, subroom.current_save_id)
                    if subroom.current_save_id is not None
                    else None
                ),
            }
            for subroom in subrooms
        ],
        "Roles": [
            {
                "AccountId": role.account_id,
                "Role": role.role,
                "LastChangedByAccountId": role.changed_by_account_id,
                "InvitedRole": 0,
            }
            for role in roles
        ] or [{"AccountId": room.creator_account_id, "Role": 255, "LastChangedByAccountId": None, "InvitedRole": 0}],
        "Tags": json.loads(settings.tags_json) if settings else [],
        "PromoImages": [],
        "LoadScreens": json.loads(settings.load_screens_json) if settings else [],
    }


def instance_dto(
    room: Room,
    account_id: int,
    private: bool = False,
    requested_subroom_id: int | None = None,
) -> dict:
    dorm = _is_dorm(room)
    if dorm:
        private = True
    instance_id = 1_000_000 + room.id if not private else secrets.randbelow(800_000_000) + 2_000_000
    if dorm:
        instance_id = 1_000_000 + account_id
    imported = BUILTIN_ROOMS_BY_ID.get(1 if dorm else room.id, {})
    subrooms = imported.get("SubRooms") or []
    persistent_subrooms = []
    if not subrooms and not dorm:
        persistent_subrooms = db.session.scalars(
            db.select(SubRoom).where(SubRoom.room_id == room.id).order_by(SubRoom.id)
        ).all()
        subrooms = [
            {
                "SubRoomId": item.id,
                "UnitySceneId": item.scene,
                "MaxPlayers": item.max_players,
                "CurrentSaveId": item.current_save_id,
            }
            for item in persistent_subrooms
        ]
    subroom = next(
        (
            item
            for item in subrooms
            if requested_subroom_id is not None
            and int(item.get("SubRoomId", -1)) == requested_subroom_id
        ),
        subrooms[0] if subrooms else None,
    )
    subroom_id = room.id if dorm else (int(subroom["SubRoomId"]) if subroom else room.id)
    location = str(subroom["UnitySceneId"]) if subroom else room.scene
    data_blob = ""
    if subroom and subroom.get("CurrentSaveId") is not None:
        current_save = db.session.get(RoomSave, int(subroom["CurrentSaveId"]))
        data_blob = current_save.data if current_save else ""
    return {
        "roomInstanceId": instance_id,
        "roomId": room.id,
        "subRoomId": subroom_id,
        "roomInstanceType": 1 if private else 0,
        "location": location,
        "dataBlob": data_blob,
        "eventId": 0,
        "clubId": 0,
        "roomCode": "",
        "photonRegion": current_app.config["PHOTON_REGION"],
        "photonRegionId": current_app.config["PHOTON_REGION"],
        "photonRoomId": f"rec.{instance_id}",
        "name": f"@{account_id}'s Dorm" if dorm else f"^{room.name}",
        "maxCapacity": room.max_players,
        "isFull": False,
        "isPrivate": private,
        "isInProgress": False,
        "EncryptVoiceChat": False,
    }


def register_protocol_routes(app: Flask) -> None:
    def discovery_document() -> dict[str, str]:
        domain = current_app.config["RECNET_DOMAIN"]
        scheme = "http" if domain.startswith("localhost") else "https"
        if current_app.config["SINGLE_HOST_MODE"]:
            base_url = f"{scheme}://{domain}"
            return {service: base_url for service in SERVICE_SUBDOMAINS}
        return {k: f"{scheme}://{v}.{domain}" for k, v in SERVICE_SUBDOMAINS.items()}

    @app.route("/", methods=["GET", "OPTIONS"])
    def discovery():
        if request.method == "OPTIONS":
            return "", 204
        return jsonify(discovery_document())

    @app.get("/api/discovery")
    def api_discovery():
        return jsonify(discovery_document())











    def upload_root() -> Path:
        path = Path(current_app.instance_path) / "uploads"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def safe_blob_path(category: str, blob_name: str) -> Path | None:
        relative = Path(blob_name.replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts:
            return None
        root = (upload_root() / category).resolve()
        candidate = (root / relative).resolve()
        return candidate if candidate == root or root in candidate.parents else None

    @app.post("/upload")
    @require_account
    def upload_blob(_account: Account):
        file_type = request.form.get("FileType", request.form.get("fileType", "0"))
        categories = {"1": "room", "2": "data", "3": "image", "4": "video", "5": "invention", "6": "roommetadata"}
        uploaded = next(iter(request.files.values()), None)
        if uploaded is None:
            explicit = request.form.get("imageName") or request.form.get("filename") or request.form.get("name")
            return (jsonify(filename=explicit), 200) if explicit else (jsonify(error="missing filename or valid upload data"), 400)
        category = categories.get(str(file_type))
        if category is None:
            return jsonify(error="missing or unknown FileType"), 400
        suffix = ".inv" if str(file_type) == "5" else ""
        blob_name = f"{datetime.now(UTC).date().isoformat()}/{uuid.uuid4()}{suffix}"
        destination = safe_blob_path(category, blob_name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        uploaded.save(destination)
        return jsonify(filename=blob_name)

    @app.get("/<category>/<path:blob_name>")
    def download_blob(category: str, blob_name: str):
        if category not in {"room", "data", "image", "video", "invention", "roommetadata"}:
            return "", 404
        candidate = safe_blob_path(category, blob_name)
        if candidate is None or not candidate.is_file():
            return "", 404
        response = send_file(candidate, mimetype="application/octet-stream", conditional=True)
        response.headers["X-Content-SHA256"] = hashlib.sha256(candidate.read_bytes()).hexdigest()
        return response




    @app.get("/<image_name>.jpg")
    def room_image(image_name: str):
        """Serve the canonical built-in room thumbnails from the Images host."""

        candidate = ROOM_IMAGE_DIR / f"{image_name}.jpg"
        if not candidate.is_file():
            candidate = ROOM_IMAGE_DIR / "DefaultProfileImage.jpg"
        response = send_file(candidate, mimetype="image/jpeg", conditional=True)
        response.headers["Cache-Control"] = "public, max-age=2592000, immutable"
        if request.args.get("sig") == "p1":
            placeholder = base64.b64encode(bytes(256)).decode("ascii")
            response.headers["Content-Signature"] = (
                f"key-id=KEY:RSA:p1.rec.net; data={placeholder}"
            )
        return response

    @app.get("/healthz")
    def health():
        return jsonify(status="ok", gameVersion=GAME_VERSION)

    @app.get("/privileges/me/restrictions")
    @require_account
    def restrictions(_account: Account):
        return jsonify([])

    @app.get("/role/<role>/<int:account_id>")
    def role_lookup(role: str, account_id: int):
        account = db.session.get(Account, account_id)
        if account is None or role not in {"developer", "moderator"}:
            return "", 404
        return jsonify(account.is_developer if role == "developer" else account.is_moderator)

    @app.get("/oculus/nonce")
    def oculus_nonce():
        return jsonify(secrets.token_hex(32))


    @app.get("/account/me")
    @require_account
    def account_me(account: Account):
        return jsonify(self_account_dto(account))

    @app.get("/account/search")
    def account_search():
        name = request.args.get("name", "")
        rows = db.session.scalars(
            db.select(Account).where(Account.username.ilike(f"{name}%")).order_by(Account.username)
        ).all()
        return jsonify([account_dto(row) for row in rows])

    @app.get("/account/bulk")
    def account_bulk():
        ids = []
        for value in request.args.getlist("id"):
            ids.extend(int(item) for item in value.split(",") if item.strip().isdigit())
        rows = (
            db.session.scalars(db.select(Account).where(Account.id.in_(ids))).all() if ids else []
        )
        by_id = {row.id: row for row in rows}
        return jsonify([account_dto(by_id[item]) for item in ids if item in by_id])

    @app.get("/account/<int:account_id>/bio")
    def account_bio(account_id: int):
        account = db.session.get(Account, account_id)
        return jsonify(accountId=account_id, bio=account.bio if account else "")

    @app.get("/account/<int:account_id>")
    def account_get(account_id: int):
        account = db.session.get(Account, account_id)
        return (jsonify(account_dto(account)), 200) if account else ("", 404)

    def update_string(field: str, form_name: str):
        account = current_account()
        if account is None:
            return "", 401
        body = request.form if request.form else (request.get_json(silent=True) or {})
        setattr(account, field, str(body.get(form_name, body.get(form_name.lower(), ""))))
        db.session.commit()
        return jsonify(success=True)

    app.add_url_rule(
        "/account/me/displayname",
        "displayname",
        lambda: update_string("display_name", "displayName"),
        methods=["PUT"],
    )
    app.add_url_rule("/account/me/bio", "bio", lambda: update_string("bio", "bio"), methods=["PUT"])
    app.add_url_rule(
        "/account/me/email", "email", lambda: update_string("email", "email"), methods=["PUT"]
    )

    @app.put("/account/me/username")
    @require_account
    def change_username(account: Account):
        body = request.form if request.form else (request.get_json(silent=True) or {})
        username = str(body.get("username", "")).strip()
        if not username or len(username) > 50 or not username.isalnum():
            return jsonify(success=False, error="That username cannot be used.", value="")
        existing = db.session.scalar(
            db.select(Account).where(func.lower(Account.username) == username.lower())
        )
        if existing is not None and existing.id != account.id:
            return jsonify(success=False, error="That username is already taken.", value="")
        account.username = username
        db.session.commit()
        return jsonify(success=True, error="", value=account_dto(account))

    @app.get("/accountprivacysettings/<int:account_id>")
    def account_privacy_settings(account_id: int):
        return jsonify(accountId=account_id, isRecentHistoryVisible=True)

    @app.get("/subscription/details/<value>")
    def subscription_details(value: str):
        if not value.isdigit():
            return jsonify({})
        return jsonify(accountId=int(value), clubId=0, subscriberCount=0)

    @app.get("/subscription/subscriberCount/<int:account_id>")
    def subscriber_count(account_id: int):
        return jsonify(0)

    @app.get("/subscription/mine/member")
    def subscription_memberships():
        return jsonify([])

    @app.get("/club/mine/created")
    @require_account
    def created_clubs(account: Account):
        clubs = db.session.scalars(
            db.select(Club).where(Club.creator_account_id == account.id).order_by(Club.id)
        ).all()
        return jsonify([club_dto(club) for club in clubs])

    @app.get("/club/mine/member")
    @require_account
    def member_clubs(account: Account):
        memberships = db.session.scalars(
            db.select(ClubMember)
            .where(ClubMember.account_id == account.id, ClubMember.membership_type >= 10)
            .order_by(ClubMember.club_id)
        ).all()
        return jsonify(
            [club_dto(club) for row in memberships if (club := db.session.get(Club, row.club_id))]
        )

    @app.get("/showcase/<int:account_id>")
    def player_showcase(account_id: int):

        return jsonify([])


    @app.get("/api/versioncheck/v4")
    def version_check():
        return jsonify(
            VersionStatus=0 if request.args.get("v") == GAME_VERSION else 1,
            UpdateNotificationStage=0,
            IsVersionIslanded=False,
            IsCrossPlayDisabled=False,
        )

    @app.get("/api/versioncheck/islandedversions")
    def islanded_versions():
        return jsonify([])

    @app.get("/api/config/v1/amplitude")
    def amplitude():
        return jsonify(AmplitudeKey="a", StatSigKey="a", RudderStackKey="a", UseRudderStack=False)

    @app.get("/api/config/v1/azurespeech")
    def azure_speech():
        return jsonify(Key="", Region="eastus", Enabled=False)

    @app.get("/api/config/v1/backtrace")
    def backtrace():
        return jsonify(ReportBudget=0, FilterType=0, SampleRate=0, CaptureNativeCrashes=0)

    @app.get("/api/config/v2")
    def api_config():
        domain = current_app.config["RECNET_DOMAIN"]
        config = {**API_CONFIG_V2, "ShareBaseUrl": f"https://{domain}/{{0}}"}
        return jsonify(config)

    @app.get("/api/gameconfigs/v1/all")
    def game_configs():
        return jsonify(GAME_CONFIGS_2023)

    @app.get("/config/<config_name>")
    def published_config(config_name: str):
        candidate = config_name
        if candidate not in PUBLISHED_CONFIGS and f"{candidate}.json" in PUBLISHED_CONFIGS:
            candidate = f"{candidate}.json"
        if candidate not in PUBLISHED_CONFIGS:
            return "", 404
        return send_file(DATA_DIR / candidate)

    @app.post("/statsigUserProperties")
    def statsig():
        return jsonify(success=True)

    @app.post("/api/gamesight/event")
    def gamesight_event():
        return "", 200

    @app.post("/data/event")
    @app.post("/data/heartbeat")
    def telemetry_ack():
        return jsonify({})

    @app.post("/pageview/consume")
    def consume_page_view():


        return jsonify(FreshnessSeconds=0.0, Url="")

    @app.post("/data/events")
    def telemetry_batch_ack():
        return jsonify([])

    @app.get("/sampling")
    def telemetry_sampling():
        return jsonify({})

    def relationship_dto(row: Relationship, viewer_id: int) -> dict:
        requester = row.requester_id == viewer_id
        relationship_type = row.relationship_type
        if not requester and relationship_type in {1, 2}:
            relationship_type = 3 - relationship_type
        prefix = "requester" if requester else "target"
        return {
            "PlayerID": row.target_id if requester else row.requester_id,
            "RelationshipType": relationship_type,
            "Favorited": int(getattr(row, f"{prefix}_favorited")),
            "Ignored": int(getattr(row, f"{prefix}_ignored")),
            "Muted": int(getattr(row, f"{prefix}_muted")),
        }

    @app.get("/api/relationships/v2/get")
    @require_account
    def relationships_get(account: Account):
        rows = db.session.scalars(
            db.select(Relationship).where(
                (Relationship.requester_id == account.id)
                | (Relationship.target_id == account.id)
            )
        ).all()
        return jsonify([relationship_dto(row, account.id) for row in rows])

    @app.route(
        "/api/relationships/v2/<action>", methods=["GET", "POST"]
    )
    @require_account
    def relationship_mutation(account: Account, action: str):
        if action not in {
            "sendfriendrequest",
            "acceptfriendrequest",
            "removefriend",
            "addfriend",
        }:
            return "", 404
        raw_target = request.args.get("id") or request.form.get("id")
        if not raw_target or not raw_target.isdigit():
            return jsonify(error="invalid player id"), 400
        target_id = int(raw_target)
        if target_id == account.id or db.session.get(Account, target_id) is None:
            return jsonify(error="invalid player id"), 400

        row = db.session.scalar(
            db.select(Relationship).where(
                ((Relationship.requester_id == account.id) & (Relationship.target_id == target_id))
                | ((Relationship.requester_id == target_id) & (Relationship.target_id == account.id))
            )
        )
        if row is None:
            row = Relationship(requester_id=account.id, target_id=target_id)
            db.session.add(row)

        if action == "sendfriendrequest":

            incoming = row.requester_id == target_id and row.relationship_type == 1
            row.relationship_type = 3 if incoming else 1
            if not incoming:
                row.requester_id, row.target_id = account.id, target_id
        elif action == "acceptfriendrequest":
            if row.requester_id == target_id and row.relationship_type == 1:
                row.relationship_type = 3
        elif action == "addfriend":
            row.relationship_type = 3
        else:
            row.relationship_type = 0
        db.session.commit()
        return jsonify(relationship_dto(row, account.id))

    def are_friends(first_id: int, second_id: int) -> bool:
        return (
            db.session.scalar(
                db.select(Relationship.id).where(
                    Relationship.relationship_type == 3,
                    (
                        (Relationship.requester_id == first_id)
                        & (Relationship.target_id == second_id)
                    )
                    | (
                        (Relationship.requester_id == second_id)
                        & (Relationship.target_id == first_id)
                    ),
                )
            )
            is not None
        )

    @app.get("/api/relationships/mutualfriends")
    @require_account
    def mutual_friends(account: Account):
        raw_target = request.args.get("id", "")
        if not raw_target.isdigit() or int(raw_target) == account.id:
            return jsonify([])
        target_id = int(raw_target)

        def friend_ids(player_id: int) -> set[int]:
            rows = db.session.scalars(
                db.select(Relationship).where(
                    Relationship.relationship_type == 3,
                    (Relationship.requester_id == player_id)
                    | (Relationship.target_id == player_id),
                )
            ).all()
            return {
                row.target_id if row.requester_id == player_id else row.requester_id
                for row in rows
            }

        mutual_ids = sorted(friend_ids(account.id) & friend_ids(target_id))[:100]
        mutuals = [db.session.get(Account, account_id) for account_id in mutual_ids]
        return jsonify(
            [
                {
                    "AccountId": mutual.id,
                    "Username": mutual.username,
                    "DisplayName": mutual.display_name,
                    "ProfileImage": mutual.profile_image,
                }
                for mutual in mutuals
                if mutual is not None
            ]
        )

    @app.post("/api/messages/v1/friendOnlineStatus")
    @require_account
    def friend_online_status(account: Account):
        relationships = db.session.scalars(
            db.select(Relationship).where(
                Relationship.relationship_type == 3,
                (Relationship.requester_id == account.id)
                | (Relationship.target_id == account.id),
            )
        ).all()
        friend_ids = {
            row.target_id if row.requester_id == account.id else row.requester_id
            for row in relationships
        }
        online = (
            db.session.scalar(
                db.select(func.count()).select_from(Presence).where(Presence.account_id.in_(friend_ids))
            )
            if friend_ids
            else 0
        )
        return jsonify(success=True, value={"FriendsOnlineCount": online or 0})

    @app.get("/api/messages/v1/favoriteFriendOnlineStatus")
    def favorite_friend_online_status():
        return jsonify([])

    @app.post("/api/messages/v1/sendMultiple")
    @require_account
    def send_multiple_messages(account: Account):
        body = request.get_json(silent=True) or {}
        recipients = body.get("ToPlayerIds", body.get("PlayerIds", []))
        if not isinstance(recipients, list):
            recipients = []
        for target in recipients:
            try:
                target_id = int(target)
            except (TypeError, ValueError):
                continue
            if db.session.get(Account, target_id) is None:
                continue
            db.session.add(
                PlayerMessage(
                    from_player_id=account.id,
                    to_player_id=target_id,
                    message_type=int(body.get("Type", 0) or 0),
                    data=str(body.get("Data", "")),
                    room_id=body.get("RoomId"),
                )
            )
        db.session.commit()
        return jsonify(success=True)

    @app.post("/hub/v1/negotiate")
    def notifications_negotiate():
        try:
            negotiate_version = int(request.args.get("negotiateVersion", "0"))
        except ValueError:
            negotiate_version = 0
        connection_id = str(uuid.uuid4())
        return jsonify(
            negotiateVersion=negotiate_version,
            connectionId=connection_id,
            connectionToken=connection_id,
            availableTransports=[{"transport": "WebSockets", "transferFormats": ["Text"]}],
        )

    @app.get("/voice/config")
    def voice_config():
        return jsonify({})


    @app.get("/rooms")
    def room_lookup():
        room = None
        room_id = request.args.get("id", "").split(",", 1)[0]
        name = request.args.get("name", "")
        if room_id.isdigit():
            room = db.session.get(Room, int(room_id))
        elif name:
            room = db.session.scalar(
                db.select(Room).where(func.lower(Room.name) == name.lower())
            )
        return jsonify(room_dto(room) if room else {})

    @app.get("/rooms/<int:room_id>")
    @app.get("/api/rooms/v1/room/<int:room_id>")
    def room_get(room_id: int):
        room = db.session.get(Room, room_id)
        return (jsonify(room_dto(room)), 200) if room else ("", 404)

    @app.get("/rooms/magic_door")
    def magic_door_room():
        """Return a playable public room for the watch's room destination resolver."""

        room = db.session.get(Room, 2)
        if room is None:
            room = db.session.scalar(
                db.select(Room).where(Room.id != 1).order_by(Room.id)
            )
        return (jsonify(room_dto(room)), 200) if room else ("", 404)

    @app.get("/rooms/name/<name>")
    def room_by_name(name: str):
        room = db.session.scalar(db.select(Room).where(func.lower(Room.name) == name.lower()))
        return (jsonify(room_dto(room)), 200) if room else ("", 404)

    @app.get("/rooms/<int:room_id>/playerdata/me")
    def room_player_data(room_id: int):


        return jsonify(Data="")

    @app.post("/api/rooms/v1/verifyRole")
    def verify_room_role():
        """Answer the room-role gate used before the client enables Maker Pen."""

        account = current_account()
        if account is None:
            return jsonify(False)

        def parameter(name: str) -> str:
            return request.form.get(name) or request.args.get(name, "")

        try:
            room_id = int(parameter("roomId"))
        except (TypeError, ValueError):
            return jsonify(False)

        room = db.session.get(Room, room_id)
        if room is None:
            return jsonify(False)




        return jsonify(room.creator_account_id == account.id or account.is_developer)

    @app.get("/api/CircuitChipLists/<list_name>")
    def circuit_chip_list(list_name: str):


        return jsonify([])

    @app.get("/api/roomkeys/v1/room")
    def room_keys_for_room():
        return jsonify([])

    @app.get("/api/keepsakes/categories")
    def keepsake_categories():
        return jsonify(Results=[], TotalResults=0)

    @app.get("/api/keepsakes/rooms/<int:room_id>")
    def room_keepsakes(room_id: int):
        return jsonify([])

    @app.get("/api/keepsakes/globalconfig")
    def keepsake_global_config():
        return jsonify({})

    @app.get("/api/inventions/v2/mine")
    def own_inventions():
        return jsonify([])

    @app.get("/api/inventions/v2/search")
    @app.get("/api/inventions/v2/batch")
    @app.get("/api/inventions/v1/toptoday")
    @app.get("/api/inventions/v1/featured")
    @app.get("/api/inventions/v1/featureddormskins")
    @app.get("/api/inventions/v1/fromcreators")
    def empty_invention_feed():


        return jsonify([])

    @app.get("/api/inventions/v1/tagfilters")
    def invention_tag_filters():
        return jsonify(PinnedFilters=[], PopularFilters=[], TrendingFilters=None)

    @app.get("/api/rooms/v1/filters")
    def room_filter_tags():
        return jsonify(
            PinnedFilters=[
                "recroomoriginal",
                "community",
                "featured",
                "quest",
                "pvp",
                "hangout",
                "game",
                "art",
                "store",
                "tutorial",
                "fandom",
                "performance",
                "action",
                "horror",
            ],
            PopularFilters=["pvp", "quest", "game", "hangout", "art"],
            TrendingFilters=["roleplay", "nomp", "rp", "casual", "fun", "action"],
        )

    @app.get("/api/playerevents/v1/tagfilters")
    def player_event_tag_filters():
        tags = [
            "workshops",
            "celebration",
            "game",
            "meetup",
            "performance",
            "coop",
            "grandopening",
            "class",
            "competition",
        ]
        return jsonify(PinnedFilters=tags, PopularFilters=tags, TrendingFilters=None)

    def event_dto(event: PlayerEvent) -> dict:
        going = db.session.scalar(
            db.select(func.count()).select_from(PlayerEventResponse).where(
                PlayerEventResponse.event_id == event.id,
                PlayerEventResponse.response_type == 0,
            )
        ) or 0
        return {
            "PlayerEventId": event.id,
            "CreatorPlayerId": event.creator_account_id,
            "RoomId": event.room_id,
            "SubRoomId": 0,
            "ClubId": 0,
            "Name": event.name,
            "Description": event.description,
            "ImageName": "",
            "StartTime": _iso(event.start_at),
            "EndTime": _iso(event.end_at),
            "AttendeeCount": going,
            "Accessibility": 1,
            "IsMultiInstance": False,
            "SupportMultiInstanceRoomChat": False,
            "DefaultBroadcastPermissions": 0,
            "CanRequestBroadcastPermissions": 0,
            "BroadcastingRoomInstanceId": None,
            "State": 0,
            "Tags": json.loads(event.tags_json),
        }

    def parse_event_time(value, fallback: datetime) -> datetime:
        if not value:
            return fallback
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return fallback

    @app.post("/api/playerevents/v2")
    @require_account
    def create_player_event(account: Account):
        body = request.get_json(silent=True) or {}
        try:
            room_id = int(body.get("RoomId", 0))
        except (TypeError, ValueError):
            room_id = 0
        if db.session.get(Room, room_id) is None or not str(body.get("Name", "")).strip():
            return "", 400
        start = parse_event_time(body.get("StartTime"), datetime.now(UTC))
        event = PlayerEvent(
            creator_account_id=account.id,
            room_id=room_id,
            name=str(body["Name"]).strip(),
            description=str(body.get("Description", "")),
            start_at=start,
            end_at=parse_event_time(body.get("EndTime"), start + timedelta(hours=1)),
            capacity=max(1, int(body.get("Capacity", 40) or 40)),
            tags_json=json.dumps(body.get("Tags", []), separators=(",", ":")),
        )
        db.session.add(event)
        db.session.flush()
        db.session.add(PlayerEventResponse(event_id=event.id, account_id=account.id, response_type=0))
        db.session.commit()
        return jsonify(Result=0, TagModifyResult=0, PlayerEvent=event_dto(event))

    @app.get("/api/playerevents/v1")
    def player_event_feed():
        now = datetime.now(UTC)
        events = db.session.scalars(db.select(PlayerEvent).where(PlayerEvent.end_at >= now).order_by(PlayerEvent.start_at)).all()
        return jsonify([event_dto(event) for event in events])

    @app.get("/api/playerevents/v1/searchlive")
    @app.get("/api/playerevents/v1/search")
    def player_event_search():
        now = datetime.now(UTC)
        query = request.args.get("query", "").lower().strip()
        events = db.session.scalars(db.select(PlayerEvent).where(PlayerEvent.end_at >= now).order_by(PlayerEvent.start_at)).all()
        if request.path.endswith("searchlive"):
            events = [event for event in events if event.start_at <= now <= event.end_at]
        elif query:
            events = [event for event in events if query in event.name.lower() or query in event.description.lower()]
        return jsonify([event_dto(event) for event in events])

    @app.get("/api/playerevents/v1/room/<int:room_id>")
    def room_player_events(room_id: int):
        events = db.session.scalars(db.select(PlayerEvent).where(PlayerEvent.room_id == room_id, PlayerEvent.end_at >= datetime.now(UTC)).order_by(PlayerEvent.start_at)).all()
        return jsonify([event_dto(event) for event in events])

    @app.get("/api/playerevents/v1/<int:event_id>")
    def get_player_event(event_id: int):
        event = db.session.get(PlayerEvent, event_id)
        return (jsonify(event_dto(event)), 200) if event else ("", 404)

    @app.post("/api/playerevents/v1/respond")
    @require_account
    def respond_to_event(account: Account):
        body = request.get_json(silent=True) or {}
        try:
            event_id, response_type = int(body.get("PlayerEventId")), int(body.get("Type"))
        except (TypeError, ValueError):
            return "", 400
        event = db.session.get(PlayerEvent, event_id)
        if event is None or response_type not in {0, 1, 2}:
            return "", 404 if event is None else 400
        response = db.session.get(PlayerEventResponse, (event_id, account.id)) or PlayerEventResponse(event_id=event_id, account_id=account.id)
        response.response_type = response_type
        db.session.add(response)
        db.session.commit()
        return jsonify(Result=0, TagModifyResult=0, PlayerEvent=event_dto(event))

    @app.get("/api/playerevents/v1/<int:event_id>/responses")
    def event_responses(event_id: int):
        rows = db.session.scalars(db.select(PlayerEventResponse).where(PlayerEventResponse.event_id == event_id)).all()
        return jsonify([{"PlayerEventId": event_id, "PlayerId": row.account_id, "Type": row.response_type, "CreatedAt": _iso(row.created_at)} for row in rows])

    @app.post("/api/playerevents/v1/bulkInvite")
    @require_account
    def bulk_invite_event(account: Account):
        body = request.get_json(silent=True) or {}
        try:
            event_id = int(body.get("PlayerEventId"))
        except (TypeError, ValueError):
            return "", 400
        event = db.session.get(PlayerEvent, event_id)
        caller_response = db.session.get(PlayerEventResponse, (event_id, account.id))
        if event is None:
            return "", 404
        if event.creator_account_id != account.id and caller_response is None:
            return "", 403
        added = []
        for raw in body.get("InvitedPlayerIds", []):
            try:
                target_id = int(raw)
            except (TypeError, ValueError):
                continue
            if db.session.get(Account, target_id) is None or db.session.get(PlayerEventResponse, (event_id, target_id)):
                continue
            db.session.add(PlayerEventResponse(event_id=event_id, account_id=target_id, response_type=0))
            added.append(target_id)
        db.session.commit()
        return jsonify(Result=0, InvitedPlayerIds=added, PlayerEvent=event_dto(event))

    @app.route("/api/playerevents/v2/<int:event_id>", methods=["PUT", "GET"])
    @require_account
    def edit_player_event(account: Account, event_id: int):
        event = db.session.get(PlayerEvent, event_id)
        if event is None:
            return "", 404
        if request.method == "GET":
            return jsonify(event_dto(event))
        if event.creator_account_id != account.id:
            return "", 403
        body = request.get_json(silent=True) or {}
        event.name = str(body.get("Name", event.name)).strip() or event.name
        event.description = str(body.get("Description", event.description))
        event.start_at = parse_event_time(body.get("StartTime"), event.start_at)
        event.end_at = parse_event_time(body.get("EndTime"), event.end_at)
        if isinstance(body.get("Tags"), list):
            event.tags_json = json.dumps(body["Tags"], separators=(",", ":"))
        db.session.commit()
        return jsonify(Result=0, TagModifyResult=0, PlayerEvent=event_dto(event))

    @app.post("/api/playerevents/v2/delete/<int:event_id>")
    @require_account
    def delete_player_event(account: Account, event_id: int):
        event = db.session.get(PlayerEvent, event_id)
        if event is None:
            return "", 404
        if event.creator_account_id != account.id:
            return "", 403
        db.session.execute(db.delete(PlayerEventResponse).where(PlayerEventResponse.event_id == event_id))
        db.session.delete(event)
        db.session.commit()
        return jsonify(Result=0)

    @app.get("/api/progressionEvents/active")
    def active_progression_events():
        return jsonify([])

    @app.get("/api/customAvatarItems/v1/featured")
    def featured_custom_avatar_items():
        return jsonify(Results=[], TotalResults=0)

    @app.get("/rooms/search")
    def room_search():
        query = request.args.get("query", request.args.get("name", ""))
        rooms = db.session.scalars(db.select(Room).where(Room.name.ilike(f"%{query}%"))).all()
        return jsonify([room_dto(room) for room in rooms])

    @app.get("/rooms/hot")
    @app.get("/rooms/recommendations")
    def hot_rooms():
        tag = request.args.get("tag", "").lower()
        try:
            skip = max(0, int(request.args.get("skip", "0")))
            take = min(200, max(1, int(request.args.get("take", "100"))))
        except ValueError:
            skip, take = 0, 100

        rooms = [
            room_dto(room)
            for room in db.session.scalars(db.select(Room).order_by(Room.id)).all()
            if not _is_dorm(room)
        ]
        rooms = [room for room in rooms if not room.get("ExcludeFromLists", False)]
        if tag in {"rro", "recroomoriginal"}:
            rooms = [room for room in rooms if room.get("IsRRO") is True]
        elif tag == "community":
            rooms = [room for room in rooms if room.get("CreatorAccountId") != 1]
        elif tag == "new":
            rooms = [room for room in reversed(rooms) if room.get("IsRRO") is not True]
        elif tag:
            rooms = [
                room
                for room in rooms
                if tag in {str(item.get("Tag", "")).lower() for item in room.get("Tags", [])}
            ]
        return jsonify(Results=rooms[skip : skip + take], TotalResults=len(rooms))

    @app.get("/rooms/curated_playlists")
    def curated_room_playlists():
        return jsonify([])

    @app.get("/playlists")
    def playlists():
        return jsonify([])

    @app.get("/rooms/carousel/rising")
    def rising_rooms():
        counts = dict(
            db.session.execute(
                db.select(Presence.room_id, func.count(Presence.account_id))
                .where(Presence.room_id.is_not(None))
                .group_by(Presence.room_id)
            ).all()
        )
        rooms = [
            room_dto(room)
            for room in db.session.scalars(db.select(Room)).all()
            if counts.get(room.id, 0) > 0 and not _is_dorm(room)
        ]
        rooms.sort(key=lambda room: (-counts.get(room["RoomId"], 0), room["RoomId"]))
        return jsonify(Results=rooms, TotalResults=len(rooms))

    @app.get("/config/categories")
    def notification_categories():
        results = [
            {
                "CategoryId": 2,
                "Importance": 0,
                "Name": "Friends",
                "Description": "Friend requests and friend activity",
                "IsMuteable": True,
            }
        ]
        return jsonify(Results=results, TotalResults=len(results))

    @app.get("/preferences")
    @require_account
    def notification_preferences(_account: Account):
        return jsonify(MutedCategories=[])

    @app.get("/club/categoryTags")
    def club_category_tags():
        return jsonify(["Social", "Creative", "Competitive", "Casual", "Entertainment"])

    @app.get("/club/search")
    def club_search():
        query = request.args.get("query", "").lower()
        category = request.args.get("category", "").lower()
        clubs = db.session.scalars(db.select(Club).where(Club.visibility == 1)).all()
        clubs = [
            club
            for club in clubs
            if (not category or club.category.lower() == category)
            and (not query or query in club.name.lower() or query in club.description.lower())
        ]
        if request.args.get("sort") == "2":
            clubs.sort(key=lambda club: club.name.lower())
        else:
            clubs.sort(key=lambda club: (-club_member_count(club.id), club.id))
        try:
            count = min(100, max(1, int(request.args.get("count", "30"))))
        except ValueError:
            count = 30
        return jsonify(
            Clubs=[club_dto(club) for club in clubs[:count]],
            ContinuationToken=None,
            TotalClubs=len(clubs),
        )

    def club_member_count(club_id: int) -> int:
        return int(
            db.session.scalar(
                db.select(func.count()).select_from(ClubMember).where(
                    ClubMember.club_id == club_id,
                    ClubMember.membership_type >= 10,
                )
            )
            or 0
        )

    def club_dto(club: Club) -> dict:
        return {
            "ClubId": club.id,
            "Name": club.name,
            "Description": club.description,
            "Category": club.category,
            "Visibility": club.visibility,
            "Joinability": club.joinability,
            "AllowJuniors": club.allow_juniors,
            "MainImageName": club.main_image_name,
            "ClubType": 0,
            "ClubhouseRoomId": club.clubhouse_room_id,
            "CreatorAccountId": club.creator_account_id,
            "IsRRO": False,
            "MinLevel": 0,
            "State": 0,
            "MemberCount": club_member_count(club.id),
        }

    def permission_dto(club_id: int, membership_type: int) -> dict:
        coowner = membership_type == 30
        moderator = membership_type == 20
        return {
            "ClubId": club_id,
            "Type": membership_type,
            "ApproveMember": coowner or moderator,
            "BanUnban": coowner or moderator,
            "CreateEvent": coowner,
            "EditDetails": coowner,
            "EditPermissionSettings": coowner,
            "PostAnnouncement": coowner,
        }

    def club_details(club: Club, viewer_id: int) -> dict:
        member = db.session.get(ClubMember, (club.id, viewer_id))
        return {
            "AdditionalImages": [],
            "Club": club_dto(club),
            "ClubId": club.id,
            "CoownerPermissions": permission_dto(club.id, 30),
            "CustomTags": [],
            "MemberPermissions": permission_dto(club.id, 10),
            "ModeratorPermissions": permission_dto(club.id, 20),
            "MyMembershipType": member.membership_type if member else 0,
        }

    @app.post("/club/create")
    @require_account
    def create_club(account: Account):
        name = request.form.get("name", request.form.get("Name", "")).strip()
        if not name or len(name) > 40:
            return jsonify(error="You must enter a valid club name.", success=False, value=None), 400
        club = Club(
            name=name,
            description=request.form.get("description", request.form.get("Description", "")),
            category=request.form.get("category", request.form.get("Category", "Social")) or "Social",
            creator_account_id=account.id,
        )
        db.session.add(club)
        db.session.flush()
        db.session.add(ClubMember(club_id=club.id, account_id=account.id, membership_type=100))
        db.session.commit()
        return jsonify(error="", success=True, value=club_details(club, account.id))

    @app.get("/club/account/<int:account_id>/created")
    def clubs_created_by_account(account_id: int):
        clubs = db.session.scalars(
            db.select(Club).where(Club.creator_account_id == account_id).order_by(Club.id)
        ).all()
        return jsonify([club_dto(club) for club in clubs])

    @app.route("/club/home/me", methods=["GET", "PUT", "DELETE"])
    @require_account
    def home_club(account: Account):
        if request.method == "DELETE":
            selected = db.session.get(HomeClub, account.id)
            if selected:
                db.session.delete(selected)
                db.session.commit()
            return jsonify(error="", success=True, value=None)
        if request.method == "PUT":
            raw_id = request.form.get("clubId", "")
            if not raw_id.isdigit() or int(raw_id) <= 0:
                return jsonify(error="Invalid clubId.", success=False, value=None), 400
            club = db.session.get(Club, int(raw_id))
            member = db.session.get(ClubMember, (int(raw_id), account.id))
            if club is None:
                return "", 404
            if member is None or member.membership_type < 10:
                return jsonify(error="You are not a member of that club.", success=False, value=None), 403
            selected = db.session.get(HomeClub, account.id)
            if selected is None:
                selected = HomeClub(account_id=account.id, club_id=club.id)
                db.session.add(selected)
            else:
                selected.club_id = club.id
            db.session.commit()
            return jsonify(error="", success=True, value=club_dto(club))
        selected = db.session.get(HomeClub, account.id)
        club = db.session.get(Club, selected.club_id) if selected else None
        return (jsonify(club_dto(club)), 200) if club else ("", 404)

    def interaction_dto(interaction: RoomInteraction) -> dict:
        return {
            "Cheered": interaction.cheered,
            "Favorited": interaction.favorited,
            "LastVisitedAt": _iso(datetime.now(UTC)),
        }

    @app.get("/rooms/favoritedby/me")
    @require_account
    def favorited_rooms(account: Account):
        rows = db.session.scalars(
            db.select(RoomInteraction)
            .where(
                RoomInteraction.account_id == account.id,
                RoomInteraction.favorited.is_(True),
            )
            .order_by(RoomInteraction.last_visited_at.desc())
        ).all()
        return jsonify([room_dto(db.session.get(Room, row.room_id)) for row in rows])

    @app.get("/rooms/visitedby/me")
    @require_account
    def visited_rooms(account: Account):
        rows = db.session.scalars(
            db.select(RoomInteraction)
            .where(
                RoomInteraction.account_id == account.id,
                RoomInteraction.last_visited_at.is_not(None),
            )
            .order_by(RoomInteraction.last_visited_at.desc())
        ).all()
        return jsonify([room_dto(db.session.get(Room, row.room_id)) for row in rows])

    @app.get("/rooms/<int:room_id>/interactionby/me")
    @require_account
    def room_interaction(account: Account, room_id: int):
        interaction = db.session.get(RoomInteraction, (account.id, room_id))
        if interaction is None:
            interaction = RoomInteraction(account_id=account.id, room_id=room_id)
            db.session.add(interaction)
        interaction.last_visited_at = datetime.now(UTC)
        db.session.commit()
        return jsonify(interaction_dto(interaction))

    @app.route(
        "/rooms/<int:room_id>/interactionby/me/<kind>", methods=["PUT", "DELETE"]
    )
    @require_account
    def change_room_interaction(account: Account, room_id: int, kind: str):
        if kind not in {"cheer", "favorite"}:
            return "", 404
        interaction = db.session.get(RoomInteraction, (account.id, room_id))
        if interaction is None:
            interaction = RoomInteraction(account_id=account.id, room_id=room_id)
            db.session.add(interaction)
        field = "cheered" if kind == "cheer" else "favorited"
        current = bool(getattr(interaction, field))
        setattr(interaction, field, not current if request.method == "PUT" else False)
        interaction.last_visited_at = datetime.now(UTC)
        db.session.commit()
        return jsonify(interaction_dto(interaction))

    @app.get("/rooms/ownedby/<int:account_id>")
    def rooms_owned_by_account(account_id: int):
        rooms = db.session.scalars(
            db.select(Room).where(Room.creator_account_id == account_id).order_by(Room.id)
        ).all()
        return jsonify([room_dto(room) for room in rooms if not _is_dorm(room)])

    @app.get("/rooms/ownedby/me")
    @require_account
    def rooms_owned_by_me(account: Account):
        rooms = db.session.scalars(
            db.select(Room).where(Room.creator_account_id == account.id).order_by(Room.id)
        ).all()
        return jsonify([room_dto(room) for room in rooms if not _is_dorm(room)])

    @app.get("/dormroom/me")
    @require_account
    def own_dorm_room(account: Account):
        return jsonify(_get_or_create_personal_dorm(account).id)

    @app.get("/rooms/createdby/me")
    @app.get("/roomserver/rooms/createdby/me")
    @require_account
    def rooms_created_by_me(account: Account):
        _get_or_create_personal_dorm(account)
        rooms = db.session.scalars(
            db.select(Room).where(Room.creator_account_id == account.id)
        ).all()
        return jsonify([room_dto(room) for room in rooms])

    def room_body() -> dict:
        return request.form.to_dict() if request.form else (request.get_json(silent=True) or {})

    def room_envelope(room: Room | None, error: str = ""):
        return jsonify(success=room is not None, error=error, value=room_dto(room) if room else None)

    def room_result(success: bool, error_id=None, error=None):
        return jsonify(Success=success, Value=None, ErrorId=error_id, Error=error)

    def owned_room(account: Account, room_id: int) -> Room | None:
        room = db.session.get(Room, room_id)
        return room if room and room.creator_account_id == account.id else None

    @app.post("/rooms/<int:source_room_id>/clone")
    @require_account
    def clone_room(account: Account, source_room_id: int):
        source = db.session.get(Room, source_room_id)
        name = str(room_body().get("name", request.args.get("name", ""))).strip()
        if source is None:
            return room_envelope(None, "This room does not exist!")
        if not name:
            return room_envelope(None, "You must enter a name for your room.")
        if db.session.scalar(db.select(Room).where(func.lower(Room.name) == name.lower())):
            return room_envelope(None, "A room with that name already exists!")
        source_profile = db.session.get(RoomProfile, source.id)
        if source_profile and not source_profile.cloning_allowed:
            return room_envelope(None, "You can't clone this room!")
        new_room = Room(
            name=name,
            description=source.description,
            scene=source.scene,
            max_players=source.max_players,
            creator_account_id=account.id,
        )
        db.session.add(new_room)
        db.session.flush()
        db.session.add(RoomProfile(room_id=new_room.id, accessibility=0, publish_state=0))
        db.session.add(RoomRole(room_id=new_room.id, account_id=account.id, role=255))
        source_subrooms = db.session.scalars(
            db.select(SubRoom).where(SubRoom.room_id == source.id).order_by(SubRoom.id)
        ).all()
        if not source_subrooms:
            imported = BUILTIN_ROOMS_BY_ID.get(source.id, {})
            source_subrooms = imported.get("SubRooms") or [
                {"Name": "Home", "UnitySceneId": source.scene, "MaxPlayers": source.max_players}
            ]
        for item in source_subrooms:
            db.session.add(
                SubRoom(
                    room_id=new_room.id,
                    name=item.name if isinstance(item, SubRoom) else item.get("Name", "Home"),
                    scene=item.scene if isinstance(item, SubRoom) else item.get("UnitySceneId", source.scene),
                    max_players=item.max_players if isinstance(item, SubRoom) else item.get("MaxPlayers", source.max_players),
                )
            )
        db.session.commit()
        return room_envelope(new_room)

    @app.put("/rooms/<int:room_id>/name")
    @app.put("/rooms/<int:room_id>/description")
    @app.put("/rooms/<int:room_id>/image")
    @require_account
    def edit_room_identity(account: Account, room_id: int):
        room = db.session.get(Room, room_id)
        if room is None:
            return room_result(False, "Rooms.DoesntExist", "This room does not exist!")
        if room.creator_account_id != account.id:
            return room_result(False, "Rooms.NotOwner", "You are not the owner of this room!")
        body = room_body()
        field = request.path.rsplit("/", 1)[-1]
        if field == "name":
            name = str(body.get("name", "")).strip()
            if not name:
                return room_result(False, "Rooms.InvalidName", "You must enter a name for your room!")
            existing = db.session.scalar(db.select(Room).where(func.lower(Room.name) == name.lower()))
            if existing and existing.id != room.id:
                return room_result(False, "Rooms.AlreadyExists", "A room with that name already exists!")
            room.name = name
        elif field == "description":
            room.description = str(body.get("description", ""))
        else:
            profile = db.session.get(RoomProfile, room.id) or RoomProfile(room_id=room.id)
            profile.image_name = str(body.get("imageName", "")).strip()
            db.session.add(profile)
        db.session.commit()
        return room_result(True)

    @app.put("/rooms/<int:room_id>/accessibility")
    @app.put("/rooms/<int:room_id>/cloning")
    @require_account
    def edit_room_visibility(account: Account, room_id: int):
        room = owned_room(account, room_id)
        if room is None:
            return room_envelope(None, "You are not the owner of this room!")
        body = room_body()
        profile = db.session.get(RoomProfile, room.id) or RoomProfile(room_id=room.id)
        if request.path.endswith("accessibility"):
            try:
                profile.accessibility = int(body.get("accessibility", 0))
            except (TypeError, ValueError):
                return room_envelope(None, "You must provide a valid accessibility!")
            profile.publish_state = 1 if profile.accessibility == 1 else 0
            profile.published_at = datetime.now(UTC) if profile.accessibility == 1 else None
        else:
            profile.cloning_allowed = str(body.get("cloningAllowed", "false")).lower() == "true"
        db.session.add(profile)
        db.session.commit()
        return room_envelope(room)

    def editable_room(account: Account, room_id: int) -> Room | None:
        room = db.session.get(Room, room_id)
        if room is None:
            return None
        role = db.session.get(RoomRole, (room_id, account.id))
        return room if room.creator_account_id == account.id or (role and role.role >= 30) else None

    def room_settings(room_id: int) -> RoomSetting:
        settings = db.session.get(RoomSetting, room_id)
        if settings is None:
            settings = RoomSetting(room_id=room_id)
            db.session.add(settings)
        return settings

    @app.put("/rooms/<int:room_id>/warning")
    @app.put("/rooms/<int:room_id>/tags")
    @app.put("/rooms/<int:room_id>/restrictions")
    @app.put("/rooms/<int:room_id>/loadscreen")
    @require_account
    def edit_extended_room_settings(account: Account, room_id: int):
        room = editable_room(account, room_id)
        if room is None:
            return "", 403
        body = room_body()
        settings = room_settings(room_id)
        action = request.path.rsplit("/", 1)[-1]
        if action == "warning":
            try:
                settings.warning_mask = int(body.get("warningMask", 0))
            except (TypeError, ValueError):
                return room_envelope(None, "You must provide a valid warning mask!")
            if "customWarning" in body:
                settings.custom_warning = str(body["customWarning"])
        elif action == "tags":
            posted_tags = request.form.getlist("tag") if request.form else body.get("tags", body.get("Tags", []))
            if isinstance(posted_tags, str):
                posted_tags = [posted_tags]
            tags = [{"Tag": str(tag).strip().lower(), "Type": 0} for tag in posted_tags if str(tag).strip()]
            settings.tags_json = json.dumps(tags, separators=(",", ":"))
        elif action == "restrictions":
            field_names = {
                "supportsscreens": "SupportsScreens",
                "supportswalkvr": "SupportsWalkVR",
                "supportsteleportvr": "SupportsTeleportVR",
                "supportsvrlow": "SupportsVRLow",
                "supportsquest2": "SupportsQuest2",
                "supportsmobile": "SupportsMobile",
                "supportsjuniors": "SupportsJuniors",
            }
            values = json.loads(settings.restrictions_json)
            for key, raw in body.items():
                if key.lower() in field_names:
                    values[field_names[key.lower()]] = str(raw).lower() == "true"
            settings.restrictions_json = json.dumps(values, separators=(",", ":"))
        else:
            image_name = str(body.get("imageName", "")).strip()
            if not image_name:
                return room_envelope(None, "You must provide an image!")
            settings.load_screens_json = json.dumps(
                [{"ImageName": image_name, "Title": str(body.get("title", "")), "Subtitle": str(body.get("subtitle", ""))}],
                separators=(",", ":"),
            )
        db.session.commit()
        return room_envelope(room)

    @app.put("/rooms/<int:room_id>/roles/<int:target_id>")
    @require_account
    def set_room_role(account: Account, room_id: int, target_id: int):
        room = owned_room(account, room_id)
        if room is None:
            return "", 403
        try:
            role_value = int(room_body().get("role"))
        except (TypeError, ValueError):
            return room_envelope(None, "You must provide a valid role!")
        role = db.session.get(RoomRole, (room_id, target_id)) or RoomRole(room_id=room_id, account_id=target_id)
        role.role = role_value
        role.changed_by_account_id = account.id
        db.session.add(role)
        db.session.commit()
        return room_envelope(room)

    @app.post("/rooms/<int:room_id>/subrooms")
    @require_account
    def create_subroom(account: Account, room_id: int):
        room = owned_room(account, room_id)
        if room is None:
            return room_envelope(None, "You are not the owner of this room!")
        name = str(room_body().get("name", "")).strip()
        if not name:
            return room_envelope(None, "You must enter a name for your subroom!")
        template = db.session.scalar(db.select(SubRoom).where(SubRoom.room_id == room.id).order_by(SubRoom.id))
        db.session.add(SubRoom(room_id=room.id, name=name, scene=template.scene if template else room.scene, max_players=template.max_players if template else room.max_players))
        db.session.commit()
        return room_envelope(room)

    @app.post("/rooms/<int:room_id>/subrooms/<int:subroom_id>/clone")
    @require_account
    def clone_subroom(account: Account, room_id: int, subroom_id: int):
        room = owned_room(account, room_id)
        source = db.session.get(SubRoom, subroom_id)
        if room is None or source is None or source.room_id != room_id:
            return room_envelope(None, "This subroom does not exist!")
        clone = SubRoom(
            room_id=room_id,
            name=f"{source.name} Copy",
            scene=source.scene,
            max_players=source.max_players,
            accessibility=source.accessibility,
        )
        db.session.add(clone)
        db.session.flush()
        if source.current_save_id is not None:
            source_save = db.session.get(RoomSave, source.current_save_id)
            copied_save = RoomSave(
                sub_room_id=clone.id,
                saved_by_account_id=account.id,
                data=source_save.data,
                description=source_save.description,
                unity_asset_id=source_save.unity_asset_id,
            )
            db.session.add(copied_save)
            db.session.flush()
            clone.current_save_id = copied_save.id
        db.session.commit()
        return room_envelope(room)

    @app.delete("/rooms/<int:room_id>/subrooms/<int:subroom_id>")
    @require_account
    def delete_subroom(account: Account, room_id: int, subroom_id: int):
        room = owned_room(account, room_id)
        subroom = db.session.get(SubRoom, subroom_id)
        if room is None or subroom is None or subroom.room_id != room_id:
            return room_envelope(None, "This subroom does not exist!")
        count = db.session.scalar(db.select(func.count()).select_from(SubRoom).where(SubRoom.room_id == room_id)) or 0
        if count <= 1:
            return room_envelope(None, "A room must have at least one subroom!")
        db.session.execute(db.delete(RoomSave).where(RoomSave.sub_room_id == subroom_id))
        db.session.delete(subroom)
        db.session.commit()
        return room_envelope(room)

    @app.route("/rooms/<int:room_id>/subrooms/<int:subroom_id>/modify", methods=["PUT"])
    @require_account
    def modify_subroom(account: Account, room_id: int, subroom_id: int):
        room = owned_room(account, room_id)
        subroom = db.session.get(SubRoom, subroom_id)
        if room is None or subroom is None or subroom.room_id != room_id:
            return room_result(False, "Rooms.DoesntExist", "This subroom does not exist!")
        body = room_body()
        if "name" in body:
            subroom.name = str(body["name"]).strip()
        if "accessibility" in body:
            names = {"private": 0, "public": 1, "unlisted": 2}
            raw = str(body["accessibility"])
            subroom.accessibility = names.get(raw.lower(), int(raw) if raw.isdigit() else 0)
        if str(body.get("maxPlayers", "")).isdigit():
            subroom.max_players = max(1, int(body["maxPlayers"]))
        db.session.commit()
        return room_result(True)

    @app.put("/rooms/<int:room_id>/subrooms/<int:subroom_id>/permissions")
    @require_account
    def set_subroom_permissions(account: Account, room_id: int, subroom_id: int):
        room = owned_room(account, room_id)
        subroom = db.session.get(SubRoom, subroom_id)
        if room is None:
            return "", 403
        if subroom is None or subroom.room_id != room_id:
            return "", 404
        entries = request.get_json(silent=True)
        if not isinstance(entries, list):
            return "", 400
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("Permission"):
                continue
            try:
                role = int(entry.get("Role", 0))
            except (TypeError, ValueError):
                continue
            key = (subroom_id, str(entry["Permission"]), role)
            stored = db.session.get(SubRoomPermission, key)
            if entry.get("Override") is False:
                if stored:
                    db.session.delete(stored)
                continue
            stored = stored or SubRoomPermission(sub_room_id=subroom_id, permission=key[1], role=role)
            stored.value = str(entry.get("Value", "True"))
            db.session.add(stored)
        db.session.commit()
        return "", 200

    @app.route("/api/rooms/v1/<int:room_id>/circuit-values", methods=["GET", "PUT", "POST", "DELETE"])
    @require_account
    def circuit_values(account: Account, room_id: int):
        if db.session.get(Room, room_id) is None:
            return "", 404
        body = room_body()
        key = str(body.get("Key", body.get("key", request.args.get("key", "")))).strip()
        per_player = str(body.get("PerPlayer", body.get("perPlayer", "false"))).lower() == "true"
        owner_id = account.id if per_player else 0
        if request.method == "GET":
            rows = db.session.scalars(db.select(CircuitValue).where(CircuitValue.room_id == room_id, CircuitValue.account_id.in_([0, account.id]))).all()
            return jsonify({row.key: json.loads(row.value_json) for row in rows})
        if not key:
            return jsonify(success=False, error="A circuit value key is required."), 400
        row = db.session.get(CircuitValue, (room_id, key, owner_id))
        if request.method == "DELETE":
            if row:
                db.session.delete(row)
                db.session.commit()
            return "", 200
        value = body.get("Value", body.get("value"))
        row = row or CircuitValue(room_id=room_id, key=key, account_id=owner_id)
        row.value_json = json.dumps(value, separators=(",", ":"))
        row.updated_at = datetime.now(UTC)
        db.session.add(row)
        db.session.commit()
        return jsonify(Key=key, Value=value, PerPlayer=per_player)

    @app.route("/api/rooms/v1/<int:room_id>/remote-video-urls", methods=["GET", "PUT", "POST"])
    @require_account
    def remote_video_urls(account: Account, room_id: int):
        if request.method == "GET":
            rows = db.session.scalars(db.select(CircuitValue).where(CircuitValue.room_id == room_id, CircuitValue.key.like("video:%"))).all()
            return jsonify({row.key.removeprefix("video:"): json.loads(row.value_json) for row in rows})
        body = room_body()
        player_key = str(body.get("PlayerId", body.get("playerId", "default")))
        url = str(body.get("Url", body.get("url", ""))).strip()
        if not url.startswith(("http://", "https://")):
            return jsonify(success=False, error="A valid HTTP or HTTPS URL is required."), 400
        row = db.session.get(CircuitValue, (room_id, f"video:{player_key}", 0)) or CircuitValue(room_id=room_id, key=f"video:{player_key}", account_id=0)
        row.value_json = json.dumps(url)
        row.updated_at = datetime.now(UTC)
        db.session.add(row)
        db.session.commit()
        return jsonify(success=True, value=url)

    @app.post("/rooms/<int:room_id>/subrooms/<int:subroom_id>/data")
    @require_account
    def save_subroom(account: Account, room_id: int, subroom_id: int):
        room = owned_room(account, room_id)
        subroom = db.session.get(SubRoom, subroom_id)
        if room is None or subroom is None or subroom.room_id != room_id:
            return room_envelope(None, "This subroom does not exist!")
        body = request.get_json(silent=True) or {}
        sub_data = body.get("SubRoomData") or {}
        save = RoomSave(
            sub_room_id=subroom.id,
            saved_by_account_id=account.id,
            data=str(sub_data.get("Filename", body.get("Data", ""))),
            description=str(body.get("Description", "")),
            unity_asset_id=body.get("UnityAssetId"),
        )
        db.session.add(save)
        db.session.flush()
        auto_publish = bool(body.get("AutoPublish")) or _is_dorm(room)
        if auto_publish:
            subroom.current_save_id = save.id
        else:
            subroom.staged_save_id = save.id
        db.session.commit()
        value = {"room": room_dto(room), "subRoomDataSave": {"id": save.id, "subRoomId": subroom.id, "dataBlob": save.data, "createdAt": _iso(save.created_at)}}
        return jsonify(success=True, error=None, value=value)

    @app.get("/rooms/<int:room_id>/subrooms/<int:subroom_id>/saves")
    @require_account
    def subroom_saves(_account: Account, room_id: int, subroom_id: int):
        subroom = db.session.get(SubRoom, subroom_id)
        if subroom is None or subroom.room_id != room_id:
            return "", 404
        saves = db.session.scalars(db.select(RoomSave).where(RoomSave.sub_room_id == subroom_id).order_by(RoomSave.id.desc())).all()
        results = [{"SubRoomDataSaveId": s.id, "SubRoomId": s.sub_room_id, "SavedByAccountId": s.saved_by_account_id, "Description": s.description, "CreatedAt": _iso(s.created_at), "DataBlob": s.data} for s in saves]
        return jsonify(Results=results, TotalResults=len(results), TotalCount=len(results))

    @app.get("/rooms/<int:room_id>/subrooms/<int:subroom_id>/saves/<int:save_id>")
    @require_account
    def get_subroom_save(_account: Account, room_id: int, subroom_id: int, save_id: int):
        subroom = db.session.get(SubRoom, subroom_id)
        save = db.session.get(RoomSave, save_id)
        if subroom is None or subroom.room_id != room_id or save is None or save.sub_room_id != subroom_id:
            return "", 404
        return jsonify(
            id=save.id,
            subRoomId=save.sub_room_id,
            dataBlob=save.data,
            unityAssetId=save.unity_asset_id,
            savedByAccountId=save.saved_by_account_id,
            description=save.description,
            createdAt=_iso(save.created_at),
        )

    @app.post("/rooms/<int:room_id>/subrooms/<int:subroom_id>/publish_save")
    @require_account
    def publish_subroom_save(account: Account, room_id: int, subroom_id: int):
        room = owned_room(account, room_id)
        subroom = db.session.get(SubRoom, subroom_id)
        try:
            save_id = int(room_body().get("subRoomDataSaveId"))
        except (TypeError, ValueError):
            return room_envelope(None, "You must provide a valid save!")
        save = db.session.get(RoomSave, save_id)
        if room is None or subroom is None or save is None or save.sub_room_id != subroom_id:
            return room_envelope(None, "That save does not exist!")
        subroom.current_save_id = save.id
        if subroom.staged_save_id == save.id:
            subroom.staged_save_id = None
        profile = db.session.get(RoomProfile, room.id) or RoomProfile(room_id=room.id)
        profile.publish_state = 1
        profile.published_at = datetime.now(UTC)
        db.session.add(profile)
        db.session.commit()
        return room_envelope(room)

    @app.post("/rooms/<int:room_id>/bans")
    @require_account
    def ban_room_player(account: Account, room_id: int):
        room = owned_room(account, room_id)
        if room is None and not (account.is_developer or account.is_moderator):
            return "", 403
        body = room_body()
        try:
            target_id = int(body.get("id"))
            mask = int(body.get("banMask", 0))
        except (TypeError, ValueError):
            return jsonify(success=False, error="You must provide a player!", value=None)
        ban = db.session.get(RoomBan, (room_id, target_id)) or RoomBan(room_id=room_id, account_id=target_id)
        ban.ban_mask, ban.banned_by_account_id = mask, account.id
        db.session.add(ban)
        db.session.commit()
        return jsonify(success=True, error="", value={"roomId": room_id, "bannedPlayerId": target_id, "banMask": mask, "bannedByAccountId": account.id})

    @app.get("/rooms/<int:room_id>/bans/<int:target_id>/isBanned")
    @app.get("/Room_server/rooms/<int:room_id>/bans/<int:target_id>/isBanned")
    @require_account
    def room_ban_status(_account: Account, room_id: int, target_id: int):
        value = db.session.get(RoomBan, (room_id, target_id)) is not None
        if request.path.startswith("/Room_server"):
            return jsonify(success=True, error=None, error_id=None, value=value)
        return jsonify(Value=value, Success=True, Error=None, error_id=None)

    @app.post("/player/login")
    @app.post("/player/notifydisconnect")
    def player_ack():
        return jsonify(errorCode=0)

    @app.post("/player/exclusivelogin")
    def exclusive_login():
        return jsonify(errorCode=0)

    @app.post("/player/logout")
    def player_logout():
        account = current_account()
        if account:
            presence = db.session.get(Presence, account.id)
            if presence:
                db.session.delete(presence)
                db.session.commit()
        return jsonify(errorCode=0)

    @app.get("/player")
    def players():
        ids = []
        for value in request.args.getlist("id"):
            ids.extend(int(item) for item in value.split(",") if item.isdigit())
        presences = (
            db.session.scalars(db.select(Presence).where(Presence.account_id.in_(ids))).all()
            if ids
            else []
        )
        by_id = {p.account_id: p for p in presences}
        result = []
        for player_id in ids:
            p = by_id.get(player_id)
            result.append(
                {
                    "playerId": player_id,
                    "isOnline": p is not None,
                    "statusVisibility": p.status_visibility if p else 0,
                    "deviceClass": p.device_class if p else 0,
                    "roomInstance": presence_instance(p) if p else None,
                }
            )
        return jsonify(result)

    def presence_instance(presence: Presence | None):
        if presence is None or presence.room_id is None:
            return None
        room = db.session.get(Room, presence.room_id)
        value = instance_dto(room, presence.account_id)
        value["roomInstanceId"] = presence.room_instance_id
        return value

    @app.post("/player/heartbeat")
    @require_account
    def heartbeat(account: Account):
        presence = db.session.get(Presence, account.id)
        if presence is None:
            presence = Presence(account_id=account.id)
            db.session.add(presence)
        body = request.get_json(silent=True) or {}
        presence.device_class = int(body.get("deviceClass", presence.device_class) or 0)
        presence.updated_at = datetime.now(UTC)
        db.session.commit()
        return jsonify(
            playerId=account.id,
            isOnline=True,
            statusVisibility=presence.status_visibility,
            deviceClass=presence.device_class,
            roomInstance=presence_instance(presence),
        )

    def avoid_juniors_value(account_id: int) -> bool:
        setting = db.session.get(PlayerSetting, (account_id, "AvoidJuniors"))
        return bool(setting and setting.value.lower() == "true")

    @app.get("/player/avoidjuniors")
    @require_account
    def get_avoid_juniors(account: Account):
        return jsonify(avoid_juniors_value(account.id))

    @app.put("/player/avoidjuniors")
    @require_account
    def set_avoid_juniors(account: Account):
        body = request.form if request.form else (request.get_json(silent=True) or {})
        raw = body.get("avoidJuniors", body.get("AvoidJuniors"))
        if raw is None:
            return jsonify(avoid_juniors_value(account.id))
        value = str(raw).lower() in {"1", "true", "yes", "on"}
        setting = db.session.get(PlayerSetting, (account.id, "AvoidJuniors"))
        if setting is None:
            setting = PlayerSetting(account_id=account.id, key="AvoidJuniors", value="False")
            db.session.add(setting)
        setting.value = str(value)
        db.session.commit()
        return jsonify(value)

    def match_room(room_ref: str, subroom_id: str | None = None):
        account = current_account()
        if account is None:
            return "", 401
        if room_ref.lower() in {"dorm", "dormroom", "none"}:
            room = _get_or_create_personal_dorm(account)
        elif room_ref.isdigit():
            room = db.session.get(Room, int(room_ref))
        else:
            room = db.session.scalar(
                db.select(Room).where(func.lower(Room.name) == room_ref.lower())
            )
        if room is None:
            return jsonify(errorCode=20, roomInstance=None)
        join_mode = request.form.get("JoinMode", "0")
        private = join_mode not in {"0", ""}
        requested_subroom_id = int(subroom_id) if subroom_id and subroom_id.isdigit() else None
        instance = instance_dto(room, account.id, private, requested_subroom_id)
        presence = db.session.get(Presence, account.id) or Presence(account_id=account.id)
        presence.room_id = room.id
        presence.room_instance_id = instance["roomInstanceId"]
        interaction = db.session.get(RoomInteraction, (account.id, room.id))
        if interaction is None:
            interaction = RoomInteraction(account_id=account.id, room_id=room.id)
            db.session.add(interaction)
        interaction.last_visited_at = datetime.now(UTC)
        db.session.add(presence)
        db.session.commit()
        return jsonify(errorCode=0, roomInstance=instance)

    @app.post("/matchmake/room/<room_ref>")
    @app.post("/matchmake/room/<room_ref>/<subroom_id>")
    @app.post("/matchmake/<room_ref>")
    @app.post("/goto/room/<room_ref>")
    def matchmake(room_ref: str, subroom_id: str | None = None):
        return match_room(room_ref, subroom_id)

    @app.post("/goto/none")
    def goto_none():
        return match_room("dorm")

    def enter_existing_instance(account: Account, target_presence: Presence) -> dict:
        room = db.session.get(Room, target_presence.room_id)
        if room is None or target_presence.room_instance_id is None:
            return {"errorCode": 20, "roomInstance": None}
        instance = instance_dto(room, account.id, _is_dorm(room))
        instance["roomInstanceId"] = target_presence.room_instance_id
        instance["photonRoomId"] = f"rec.{target_presence.room_instance_id}"
        own_presence = db.session.get(Presence, account.id) or Presence(account_id=account.id)
        own_presence.room_id = room.id
        own_presence.room_instance_id = target_presence.room_instance_id
        own_presence.updated_at = datetime.now(UTC)
        db.session.add(own_presence)
        db.session.commit()
        return {"errorCode": 0, "roomInstance": instance}

    @app.post("/matchmake/player/<int:player_id>")
    @require_account
    def follow_friend(account: Account, player_id: int):
        if player_id == account.id or not are_friends(account.id, player_id):
            return jsonify(errorCode=20, roomInstance=None)
        target_presence = db.session.get(Presence, player_id)
        if target_presence is None or target_presence.room_id is None:
            return jsonify(errorCode=20, roomInstance=None)
        return jsonify(enter_existing_instance(account, target_presence))

    @app.post("/invite")
    @require_account
    def invite_to_room(account: Account):
        raw_player_id = request.form.get("playerId", "")
        raw_instance_id = request.form.get("roomInstanceId", "")
        if not raw_player_id.isdigit() or int(raw_player_id) <= 0:
            return "", 400
        to_player_id = int(raw_player_id)
        if db.session.get(Account, to_player_id) is None:
            return "", 400
        instance_id = int(raw_instance_id) if raw_instance_id.isdigit() else None
        presence = db.session.get(Presence, account.id)
        room_id = presence.room_id if presence and presence.room_instance_id == instance_id else None
        invite = RoomInvite(
            from_player_id=account.id,
            to_player_id=to_player_id,
            room_id=room_id,
            room_instance_id=instance_id,
        )
        db.session.add(invite)
        db.session.flush()
        room = db.session.get(Room, room_id) if room_id else None
        data = json.dumps(
            {
                "InviteId": invite.id,
                "Name": f"^{room.name}" if room else "",
                "InviteMode": 22,
            },
            separators=(",", ":"),
        )
        db.session.add(
            PlayerMessage(
                from_player_id=account.id,
                to_player_id=to_player_id,
                message_type=6,
                data=data,
                room_id=room_id,
            )
        )
        db.session.commit()
        return jsonify(
            RoomInviteId=invite.id,
            FromPlayerId=account.id,
            ToPlayerId=to_player_id,
            RoomId=room_id,
        )

    @app.post("/matchmake/invite/<int:invite_id>")
    @require_account
    def accept_room_invite(account: Account, invite_id: int):
        invite = db.session.get(RoomInvite, invite_id)
        if invite is None:
            return jsonify(errorCode=40, roomInstance=None)
        if invite.to_player_id != account.id:
            return jsonify(errorCode=76, roomInstance=None)
        target_presence = db.session.get(Presence, invite.from_player_id)
        if target_presence is None or target_presence.room_id is None:
            return jsonify(errorCode=2, roomInstance=None)
        return jsonify(enter_existing_instance(account, target_presence))

    @app.get("/photon_access_token")
    @require_account
    def photon_access_token(account: Account):
        def permission(name: str, role: int, override: bool) -> dict:
            return {
                "Override": override,
                "Permission": name,
                "Role": role,
                "Type": 0,
                "Value": "True",
            }

        permissions = [
            permission("CAN_USE_ROOM_RESET_BUTTON", 0, True),
            permission("CAN_USE_DELETE_ALL_BUTTON", 0, True),
            permission("CAN_SAVE_INVENTIONS", 0, True),
            permission("CAN_SPAWN_INVENTIONS", 0, True),
            permission("CAN_USE_PLAY_GIZMOS_TOGGLE", 0, True),
            permission("CAN_USE_MAKER_PEN", 30, False),
            permission("CAN_USE_ROOM_RESET_BUTTON", 30, True),
            permission("CAN_USE_DELETE_ALL_BUTTON", 30, True),
            permission("CAN_SAVE_INVENTIONS", 30, True),
            permission("CAN_SPAWN_INVENTIONS", 30, True),
            permission("CAN_USE_PLAY_GIZMOS_TOGGLE", 30, True),
        ]
        if account.is_developer or account.id in {1, 2, 3}:
            permissions.insert(0, permission("CAN_USE_MAKER_PEN", 0, True))

        presence = db.session.get(Presence, account.id)
        if presence and presence.room_id is not None:
            subroom = db.session.scalar(
                db.select(SubRoom)
                .where(SubRoom.room_id == presence.room_id)
                .order_by(SubRoom.id)
            )
            if subroom:
                overrides = db.session.scalars(
                    db.select(SubRoomPermission).where(
                        SubRoomPermission.sub_room_id == subroom.id
                    )
                ).all()
                for override in overrides:
                    permissions = [
                        item
                        for item in permissions
                        if not (
                            item["Permission"] == override.permission
                            and item["Role"] == override.role
                        )
                    ]
                    permissions.append(
                        {
                            "Override": True,
                            "Permission": override.permission,
                            "Role": override.role,
                            "Type": 0,
                            "Value": override.value,
                        }
                    )
        return jsonify(
            Permissions=permissions,
            PhotonAccessToken="",
            RoomInstanceId=presence.room_instance_id if presence else None,
        )

    @app.post("/roominstance/<room_instance_id>/reportjoinresult")
    def report_join_result(room_instance_id: str):
        return "", 200

    def live_instance(instance_id: int):
        return db.session.scalar(
            db.select(Presence).where(Presence.room_instance_id == instance_id).limit(1)
        )

    def instance_state(instance_id: int, presence: Presence) -> RoomInstanceState:
        state = db.session.get(RoomInstanceState, instance_id)
        if state is None:
            state = RoomInstanceState(
                room_instance_id=instance_id,
                room_id=presence.room_id,
            )
            db.session.add(state)
        return state

    @app.put("/roominstance/<int:room_instance_id>/inprogress")
    @require_account
    def set_instance_in_progress(_account: Account, room_instance_id: int):
        presence = live_instance(room_instance_id)
        if presence is None or presence.room_id is None:
            return "", 404
        value = str(request.form.get("inProgress", "false")).lower() == "true"
        state = instance_state(room_instance_id, presence)
        state.in_progress = value
        state.updated_at = datetime.now(UTC)
        db.session.commit()
        return "", 200

    @app.post("/roominstance/<int:room_instance_id>/markprivate")
    @require_account
    def mark_instance_private(account: Account, room_instance_id: int):
        presence = live_instance(room_instance_id)
        if presence is None or presence.room_id is None:
            return "", 404
        room = db.session.get(Room, presence.room_id)
        role = db.session.get(RoomRole, (presence.room_id, account.id))
        if room is None or not (
            room.creator_account_id == account.id or (role is not None and role.role >= 1)
        ):
            return "", 403
        state = instance_state(room_instance_id, presence)
        state.is_private = True
        state.updated_at = datetime.now(UTC)
        db.session.commit()
        return "", 200

    def room_comment_dto(comment: RoomComment) -> dict:
        return {
            "CommentId": comment.id,
            "RoomId": comment.room_id,
            "SubRoomId": comment.sub_room_id,
            "AccountId": comment.account_id,
            "CreatedAt": _iso(comment.created_at),
            "Message": comment.message,
            "Style": comment.style,
            "Unread": True,
            "PositionX": comment.position_x,
            "PositionY": comment.position_y,
            "PositionZ": comment.position_z,
        }

    @app.get("/comments/get/<int:room_id>")
    def room_comments_get(room_id: int):
        try:
            count = max(1, min(int(request.args.get("count", 100)), 500))
        except ValueError:
            count = 100
        try:
            min_id = int(request.args.get("minId", -1))
        except ValueError:
            min_id = -1
        query = db.select(RoomComment).where(
            RoomComment.room_id == room_id,
            RoomComment.id > min_id,
        )
        sub_room_id = request.args.get("subRoomId")
        if sub_room_id is not None:
            try:
                query = query.where(RoomComment.sub_room_id == int(sub_room_id))
            except ValueError:
                pass
        comments = db.session.scalars(query.order_by(RoomComment.id.desc()).limit(count)).all()
        return jsonify([room_comment_dto(comment) for comment in comments])

    @app.post("/comments/create/<int:room_id>")
    @require_account
    def room_comments_create(account: Account, room_id: int):
        message = str(request.form.get("message", "")).strip()[:1000]
        try:
            sub_room_id = int(request.form["subRoomId"])
        except (KeyError, TypeError, ValueError):
            return "", 400
        if not message:
            return "", 400

        def number(name: str) -> float:
            try:
                value = float(request.form.get(name, 0))
                return value if math.isfinite(value) else 0.0
            except (TypeError, ValueError):
                return 0.0

        try:
            style = int(request.form.get("style", 0))
        except (TypeError, ValueError):
            style = 0
        comment = RoomComment(
            room_id=room_id,
            sub_room_id=sub_room_id,
            account_id=account.id,
            message=message,
            style=style,
            position_x=number("positionX"),
            position_y=number("positionY"),
            position_z=number("positionZ"),
        )
        db.session.add(comment)
        db.session.commit()
        return jsonify(room_comment_dto(comment))

    @app.get("/settings/partyinvite")
    @require_account
    def party_invite_settings(_account: Account):
        return jsonify(InviteLinkLifetimeInMinutes=60)

    @app.get("/thread/party")
    @require_account
    def party_thread(_account: Account):
        return jsonify({})

    def form_ids(name: str = "ids") -> list[int]:
        result = []
        for raw in request.form.getlist(name):
            for value in str(raw).split(","):
                if value.strip().isdigit():
                    result.append(int(value))
        return result

    def chat_members(thread_id: int) -> list[int]:
        return list(
            db.session.scalars(
                db.select(ChatThreadMember.account_id)
                .where(ChatThreadMember.thread_id == thread_id)
                .order_by(ChatThreadMember.account_id)
            ).all()
        )

    def chat_message_dto(message: ChatMessage, pascal: bool = False) -> dict:
        values = {
            "chatMessageId": message.id,
            "chatThreadId": message.thread_id,
            "senderPlayerId": message.sender_account_id,
            "timeSent": _iso(message.created_at),
            "contents": message.contents,
            "moderationState": message.moderation_state,
        }
        return {key[0].upper() + key[1:]: value for key, value in values.items()} if pascal else values

    def chat_thread_dto(
        thread: ChatThread,
        member: ChatThreadMember,
        *,
        with_messages: bool,
        limit: int = 50,
    ) -> dict:
        messages = db.session.scalars(
            db.select(ChatMessage)
            .where(ChatMessage.thread_id == thread.id)
            .order_by(ChatMessage.id.desc())
            .limit(limit)
        ).all()
        result = {
            "chatThreadId": thread.id,
            "playerIds": chat_members(thread.id),
            "lastReadMessageId": member.last_read_message_id,
            "chatThreadName": thread.name,
            "chatThreadType": 0,
            "snoozedUntil": _iso(member.snoozed_until) if member.snoozed_until else None,
            "isFavorited": member.is_favorited,
        }
        if with_messages:
            result["messages"] = [chat_message_dto(message) for message in messages]
        else:
            result["latestMessage"] = chat_message_dto(messages[0]) if messages else None
        return result

    def find_or_create_chat(account_id: int, requested_ids: list[int]):
        members = sorted({account_id, *requested_ids})
        if len(members) < 2 or len(members) > 50:
            return None
        memberships = db.session.scalars(
            db.select(ChatThreadMember).where(ChatThreadMember.account_id == account_id)
        ).all()
        for membership in memberships:
            if chat_members(membership.thread_id) == members:
                return db.session.get(ChatThread, membership.thread_id), membership
        thread = ChatThread()
        db.session.add(thread)
        db.session.flush()
        for member_id in members:
            if db.session.get(Account, member_id) is not None:
                db.session.add(ChatThreadMember(thread_id=thread.id, account_id=member_id))
        db.session.flush()
        membership = db.session.get(ChatThreadMember, (thread.id, account_id))
        return thread, membership

    def chat_limit(default: int = 50) -> int:
        raw = request.args.get("messageCount", request.args.get("MessageCount", default))
        try:
            return max(1, min(int(raw), 100))
        except (TypeError, ValueError):
            return default

    @app.get("/thread")
    @require_account
    def chat_thread_list(account: Account):
        memberships = db.session.scalars(
            db.select(ChatThreadMember).where(ChatThreadMember.account_id == account.id)
        ).all()
        threads = []
        for membership in memberships:
            thread = db.session.get(ChatThread, membership.thread_id)
            if thread:
                threads.append(chat_thread_dto(thread, membership, with_messages=False))
        threads.sort(
            key=lambda item: (item["latestMessage"] or {}).get("chatMessageId", 0), reverse=True
        )
        return jsonify(threads[: chat_limit()])

    @app.post("/thread/withmembers")
    @require_account
    def chat_with_members(account: Account):
        found = find_or_create_chat(account.id, form_ids())
        if found is None:
            return "", 400
        thread, membership = found
        db.session.commit()
        return jsonify(chat_thread_dto(thread, membership, with_messages=True))

    @app.get("/thread/<int:thread_id>")
    @require_account
    def chat_thread_get(account: Account, thread_id: int):
        thread = db.session.get(ChatThread, thread_id)
        membership = db.session.get(ChatThreadMember, (thread_id, account.id))
        if thread is None or membership is None:
            return "", 404
        return jsonify(
            chat_thread_dto(thread, membership, with_messages=True, limit=chat_limit())
        )

    def post_chat_message(account: Account, thread_id: int):
        thread = db.session.get(ChatThread, thread_id)
        membership = db.session.get(ChatThreadMember, (thread_id, account.id))
        contents = str(request.form.get("messageContents", request.form.get("contents", ""))).strip()
        if thread is None or membership is None:
            return jsonify(ChatMessage=None, ChatResult=3, chatResult=3, chatThread=None)
        if not contents:
            return jsonify(ChatMessage=None, ChatResult=1, chatResult=1, chatThread=None)
        message = ChatMessage(thread_id=thread_id, sender_account_id=account.id, contents=contents)
        db.session.add(message)
        db.session.flush()
        membership.last_read_message_id = message.id
        db.session.commit()
        return jsonify(
            ChatMessage=chat_message_dto(message, pascal=True),
            ChatResult=0,
            chatResult=0,
            chatThread=chat_thread_dto(thread, membership, with_messages=True),
        )

    @app.post("/thread/<int:thread_id>")
    @require_account
    def chat_thread_post(account: Account, thread_id: int):
        return post_chat_message(account, thread_id)

    @app.post("/thread/<int:thread_id>/message")
    @require_account
    def chat_thread_message_post(account: Account, thread_id: int):
        return post_chat_message(account, thread_id)

    @app.get("/thread/<int:thread_id>/message")
    @require_account
    def chat_thread_messages(account: Account, thread_id: int):
        if db.session.get(ChatThreadMember, (thread_id, account.id)) is None:
            return "", 404
        messages = db.session.scalars(
            db.select(ChatMessage)
            .where(ChatMessage.thread_id == thread_id)
            .order_by(ChatMessage.id.desc())
            .limit(chat_limit(16))
        ).all()
        return jsonify([chat_message_dto(message) for message in messages])

    @app.get("/thread/chatPrivacySetting")
    @require_account
    def get_chat_privacy(account: Account):
        settings = {
            row.key: row.value
            for row in db.session.scalars(
                db.select(PlayerSetting).where(PlayerSetting.account_id == account.id)
            ).all()
        }
        return jsonify(
            playerId=account.id,
            directMessagePrivacySetting=int(settings.get("directMessagePrivacySetting", 0)),
            groupChatPrivacySetting=int(settings.get("groupChatPrivacySetting", 0)),
        )

    @app.put("/thread/chatPrivacySetting")
    @require_account
    def set_chat_privacy(account: Account):
        enum = {"Friends": 0, "Favorites": 1, "NoOne": 2}
        for key in ("directMessagePrivacySetting", "groupChatPrivacySetting"):
            if key not in request.form:
                continue
            raw = request.form[key]
            value = enum.get(raw, int(raw) if raw.isdigit() and int(raw) in range(3) else None)
            if value is None:
                continue
            setting = db.session.get(PlayerSetting, (account.id, key))
            if setting is None:
                setting = PlayerSetting(account_id=account.id, key=key)
                db.session.add(setting)
            setting.value = str(value)
        db.session.commit()
        return get_chat_privacy.__wrapped__(account)

    @app.get("/thread/checkCanSendDirectMessageWithPrivacySetting")
    @require_account
    def can_send_direct_message(_account: Account):
        return jsonify(0)

    @app.route("/thread/<int:thread_id>/rename", methods=["POST", "PUT"])
    @require_account
    def rename_chat_thread(account: Account, thread_id: int):
        membership = db.session.get(ChatThreadMember, (thread_id, account.id))
        thread = db.session.get(ChatThread, thread_id)
        if membership is None or thread is None:
            return jsonify(3)
        thread.name = str(request.form.get("name", "")).strip()[:128]
        db.session.commit()
        return jsonify(0)

    @app.post("/thread/<int:thread_id>/favorite")
    @require_account
    def favorite_chat_thread(account: Account, thread_id: int):
        membership = db.session.get(ChatThreadMember, (thread_id, account.id))
        if membership is None:
            return jsonify(3)
        membership.is_favorited = str(request.form.get("isFavorite", "true")).lower() == "true"
        db.session.commit()
        return jsonify(0)

    @app.post("/thread/<int:thread_id>/message/<int:message_id>/read")
    @require_account
    def read_chat_message(account: Account, thread_id: int, message_id: int):
        membership = db.session.get(ChatThreadMember, (thread_id, account.id))
        message = db.session.get(ChatMessage, message_id)
        if membership is None or message is None or message.thread_id != thread_id:
            return jsonify(3)
        membership.last_read_message_id = max(membership.last_read_message_id, message_id)
        db.session.commit()
        return jsonify(0)

    @app.post("/thread/<int:thread_id>/member/<int:player_id>")
    @require_account
    def add_chat_member(account: Account, thread_id: int, player_id: int):
        if db.session.get(ChatThreadMember, (thread_id, account.id)) is None:
            return jsonify(3)
        if db.session.get(Account, player_id) is None:
            return jsonify(1)
        if db.session.get(ChatThreadMember, (thread_id, player_id)) is not None:
            return jsonify(4)
        db.session.add(ChatThreadMember(thread_id=thread_id, account_id=player_id))
        db.session.commit()
        return jsonify(0)

    @app.route("/thread/<int:thread_id>/leave", methods=["POST", "DELETE"])
    @require_account
    def leave_chat_thread(account: Account, thread_id: int):
        membership = db.session.get(ChatThreadMember, (thread_id, account.id))
        if membership is None:
            return jsonify(3)
        db.session.delete(membership)
        db.session.commit()
        return jsonify(0)


    @app.get("/api/avatar/v1/defaultunlocked")
    def default_unlocked_avatar_items():
        return jsonify(FULL_AVATAR_ITEMS)

    @app.get("/api/avatar/v4/items")
    def avatar_items_v4():
        return jsonify([_avatar_item_v4(item) for item in FULL_AVATAR_ITEMS])

    @app.post("/api/avatar/v1/lockeditems/bulk")
    def locked_avatar_items_bulk():
        requested = (request.get_json(silent=True) or {}).get("AvatarItemDescriptions", [])
        if not requested:
            return jsonify(FULL_AVATAR_ITEMS)

        descriptions = {str(description) for description in requested}
        return jsonify(
            [item for item in FULL_AVATAR_ITEMS if item.get("AvatarItemDesc") in descriptions]
        )

    @app.get("/api/avatar/v2")
    @require_account
    def own_avatar_v2(account: Account):


        state = db.session.get(AvatarState, account.id)
        return jsonify(json.loads(state.data) if state else DEFAULT_AVATAR)

    @app.post("/api/avatar/v2/set")
    @require_account
    def set_own_avatar_v2(account: Account):
        avatar = request.get_json(silent=True)
        if not isinstance(avatar, dict):
            return "", 400
        state = db.session.get(AvatarState, account.id)
        if state is None:
            state = AvatarState(account_id=account.id, data="{}")
            db.session.add(state)
        state.data = json.dumps(avatar, separators=(",", ":"))
        state.updated_at = datetime.now(UTC)
        db.session.commit()
        return jsonify(avatar)

    @app.get("/api/avatar/v3/saved")
    @require_account
    def saved_outfits_v3(account: Account):
        rows = db.session.scalars(
            db.select(SavedOutfit)
            .where(SavedOutfit.account_id == account.id)
            .order_by(SavedOutfit.slot)
        ).all()
        return jsonify([json.loads(row.data) for row in rows])

    @app.post("/api/avatar/v3/saved/set")
    @require_account
    def set_saved_outfit_v3(account: Account):
        outfit = request.get_json(silent=True)
        if not isinstance(outfit, dict) or not isinstance(outfit.get("Slot"), int):
            return "", 400
        slot = outfit["Slot"]
        row = db.session.get(SavedOutfit, (account.id, slot))
        if row is None:
            row = SavedOutfit(account_id=account.id, slot=slot, data="{}")
            db.session.add(row)
        row.data = json.dumps(outfit, separators=(",", ":"))
        row.updated_at = datetime.now(UTC)
        db.session.commit()
        return jsonify(outfit)

    @app.get("/api/images/v2/named")
    def named_images_v2():
        return jsonify([])

    @app.get("/api/images/v5/player/<int:player_id>")
    @app.get("/api/images/v4/player/<int:player_id>")
    def player_images(player_id: int):
        rows = db.session.scalars(
            db.select(PlayerImage)
            .where(PlayerImage.account_id == player_id)
            .order_by(PlayerImage.id.desc())
        ).all()
        return jsonify([player_image_dto(row) for row in rows])

    def player_image_dto(image: PlayerImage) -> dict:
        return {
            "Id": image.id,
            "PlayerId": image.account_id,
            "ImageName": image.image_name,
            "RoomId": image.room_id,
            "Caption": image.caption,
            "CreatedAt": _iso(image.created_at),
        }

    @app.post("/api/images/v4/uploadsaved")
    @require_account
    def upload_saved_image(account: Account):
        body = request.form if request.form else (request.get_json(silent=True) or {})
        image = PlayerImage(
            account_id=account.id,
            image_name=str(body.get("ImageName", body.get("imageName", ""))),
            room_id=int(body["RoomId"]) if str(body.get("RoomId", "")).isdigit() else None,
            caption=str(body.get("Caption", "")),
        )
        db.session.add(image)
        db.session.commit()
        return jsonify(player_image_dto(image))

    @app.get("/api/images/v5/bulk")
    def bulk_images_v5():
        ids = _query_ids()
        for value in request.args.getlist("ids"):
            ids.extend(int(item) for item in value.split(",") if item.strip().isdigit())
        images = db.session.scalars(db.select(PlayerImage).where(PlayerImage.id.in_(ids))).all() if ids else []
        return jsonify([player_image_dto(image) for image in images])

    @app.get("/api/messages/v2/get")
    @require_account
    def messages_v2(account: Account):
        messages = db.session.scalars(
            db.select(PlayerMessage)
            .where(PlayerMessage.to_player_id == account.id)
            .order_by(PlayerMessage.id.desc())
        ).all()
        return jsonify(
            [
                {
                    "Id": message.id,
                    "FromPlayerId": message.from_player_id,
                    "ToPlayerId": message.to_player_id,
                    "Type": message.message_type,
                    "Data": message.data,
                    "RoomId": message.room_id,
                }
                for message in messages
            ]
        )

    def received_gift_dto(gift: ReceivedGift) -> dict:
        return {**json.loads(gift.data_json), "Id": gift.id, "CreatedAt": _iso(gift.created_at)}

    @app.get("/api/avatar/v2/gifts")
    @require_account
    def pending_avatar_gifts(account: Account):
        gifts = db.session.scalars(
            db.select(ReceivedGift)
            .where(ReceivedGift.account_id == account.id)
            .order_by(ReceivedGift.id)
        ).all()
        return jsonify([received_gift_dto(gift) for gift in gifts])

    @app.post("/api/avatar/v2/gifts/consume")
    def consume_avatar_gift():
        account = current_account()
        try:
            gift_id = int(request.form.get("Id", 0))
        except (TypeError, ValueError):
            gift_id = 0
        gift = db.session.get(ReceivedGift, gift_id) if gift_id else None
        if gift is not None and account is not None:
            if gift.account_id != account.id:
                return "", 403
            db.session.delete(gift)
            db.session.commit()
        return jsonify(error="", success=True, value=None)

    @app.post("/api/messages/v3/delete")
    @require_account
    def delete_messages(account: Account):
        message_ids = (request.get_json(silent=True) or {}).get("MessageIds", [])
        if message_ids:
            db.session.execute(
                db.delete(PlayerMessage).where(
                    PlayerMessage.to_player_id == account.id,
                    PlayerMessage.id.in_(message_ids),
                )
            )
            db.session.commit()
        return "", 200

    @app.get("/api/quickPlay/v1/getandclear")
    def quick_play_get_and_clear():
        return jsonify(RoomName=None, ActionCode=None, TargetPlayerId=None)

    @app.put("/player/photonregionpings")
    @app.put("/player/gameserverregionpings")
    @app.put("/player/statusvisibility")
    def player_state_ack():
        return "", 200

    @app.get("/api/equipment/v2/getUnlocked")
    def all_equipment_unlocked():
        account = current_account()
        result = copy.deepcopy(ALL_UNLOCKS["equipment"])
        if account is not None:
            favorites = {
                row.modification_guid: row.favorited
                for row in db.session.scalars(
                    db.select(EquipmentPreference).where(
                        EquipmentPreference.account_id == account.id
                    )
                ).all()
            }
            for item in result:
                guid = str(item.get("ModificationGuid", ""))
                if guid in favorites:
                    item["Favorited"] = favorites[guid]
        return jsonify(result)

    @app.route("/api/equipment/v1/update", methods=["POST", "PUT"])
    @require_account
    def update_equipment(account: Account):
        body = request.get_json(silent=True)
        if not isinstance(body, list):
            return "", 400
        known_guids = {str(item.get("ModificationGuid", "")) for item in ALL_UNLOCKS["equipment"]}
        for item in body:
            if not isinstance(item, dict):
                continue
            guid = str(item.get("ModificationGuid", ""))
            if not guid or guid not in known_guids:
                continue
            preference = db.session.get(EquipmentPreference, (account.id, guid))
            if preference is None:
                preference = EquipmentPreference(account_id=account.id, modification_guid=guid)
                db.session.add(preference)
            preference.favorited = item.get("Favorited") is True
        db.session.commit()
        return "", 200

    @app.get("/api/consumables/v2/getUnlocked")
    def all_consumables_unlocked():
        account = current_account()
        if account is None:
            return jsonify(ALL_UNLOCKS["consumables"])
        overrides = {
            row.consumable: row.quantity
            for row in db.session.scalars(
                db.select(ConsumableBalance).where(ConsumableBalance.account_id == account.id)
            ).all()
        }
        result = copy.deepcopy(ALL_UNLOCKS["consumables"])
        for item in result:
            if item["ConsumableItemDesc"] in overrides:
                item["Count"] = overrides[item["ConsumableItemDesc"]]
        return jsonify(result)

    @app.post("/api/consumables/v1/consume")
    @require_account
    def consume_item(account: Account):
        body = request.get_json(silent=True) or {}
        try:
            consumable_id = int(body.get("Id"))
            delta = max(1, int(body.get("DeltaCount", 1) or 1))
        except (TypeError, ValueError):
            return jsonify(False)
        item = next(
            (
                value
                for value in ALL_UNLOCKS["consumables"]
                if consumable_id in value.get("Ids", [])
            ),
            None,
        )
        if item is None:
            return jsonify(False)
        description = item["ConsumableItemDesc"]
        balance = db.session.get(ConsumableBalance, (account.id, description))
        if balance is None:
            balance = ConsumableBalance(
                account_id=account.id,
                consumable=description,
                quantity=int(item.get("Count", 0)),
            )
            db.session.add(balance)
        if balance.quantity < delta:
            return jsonify(False)
        balance.quantity -= delta
        db.session.commit()
        return jsonify(True)

    @app.get("/api/customAvatarItems/v1/isCreationAllowedForAccount")
    def custom_avatar_creation_allowed():
        return jsonify(success=True, value=None)

    @app.get("/econ/customAvatarItems/v1/owned")
    def owned_custom_avatar_items():
        return jsonify(Results=[], TotalResults=0)

    @app.get("/api/customAvatarItems/v2/fromCreator/<int:account_id>")
    def custom_avatar_items_from_creator(account_id: int):
        return jsonify(Results=[], TotalResults=0)

    @app.get("/api/objectives/v1/myprogress")
    def objective_progress():
        return jsonify(MY_PROGRESS)

    @app.post("/api/objectives/v1/updateobjective")
    @app.post("/api/objectives/v1/cleargroup")
    def update_objective_progress():


        return jsonify(success=True)

    @app.post("/api/gamerewards/v1/request")
    def request_game_rewards():
        account = current_account()
        body = request.form if request.form else (request.get_json(silent=True) or {})
        session_id = str(
            body.get(
                "GameSessionId",
                body.get("gameSessionId", body.get("RoomInstanceId", body.get("roomInstanceId", ""))),
            )
        ).strip()
        if account is None or not session_id:
            return jsonify(Rewards=[], Success=True)
        if len(session_id) > 128:
            return jsonify(Rewards=[], Success=False, Error="Invalid game session."), 400

        previous = db.session.scalar(
            db.select(TokenTransaction).where(
                TokenTransaction.account_id == account.id,
                TokenTransaction.kind == "game_reward",
                TokenTransaction.reference == session_id,
            )
        )
        if previous is not None:
            return jsonify(Rewards=[], Success=True, Balance=account.token_balance)

        day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        earned_today = db.session.scalar(
            db.select(func.coalesce(func.sum(TokenTransaction.amount), 0)).where(
                TokenTransaction.account_id == account.id,
                TokenTransaction.kind == "game_reward",
                TokenTransaction.created_at >= day_start,
            )
        )
        reward = max(0, int(current_app.config["GAME_REWARD_TOKENS"]))
        daily_limit = max(0, int(current_app.config["DAILY_GAME_REWARD_LIMIT"]))
        reward = min(reward, max(0, daily_limit - int(earned_today or 0)))
        if reward == 0:
            return jsonify(Rewards=[], Success=True, Balance=account.token_balance)

        account.token_balance += reward
        db.session.add(
            TokenTransaction(
                account_id=account.id,
                amount=reward,
                kind="game_reward",
                reference=session_id,
            )
        )
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            refreshed = db.session.get(Account, account.id)
            return jsonify(Rewards=[], Success=True, Balance=refreshed.token_balance)
        return jsonify(
            Rewards=[{"CurrencyType": 2, "Amount": reward}],
            Success=True,
            Balance=account.token_balance,
        )

    def leaderboard_body() -> dict:
        return request.form.to_dict() if request.form else (request.get_json(silent=True) or {})

    @app.post("/leaderboard/CheckAndSetStat")
    @require_account
    def set_leaderboard_stat(account: Account):
        body = leaderboard_body()
        board = str(body.get("LeaderboardName", body.get("StatName", body.get("leaderboard", "default"))))
        try:
            score = int(body.get("Score", body.get("Value", 0)) or 0)
        except (TypeError, ValueError):
            score = 0
        row = db.session.get(LeaderboardScore, (account.id, board)) or LeaderboardScore(account_id=account.id, leaderboard=board)
        row.score = max(row.score or 0, score)
        row.updated_at = datetime.now(UTC)
        db.session.add(row)
        db.session.commit()
        return jsonify(Success=True, Score=row.score, Rank=1)

    @app.post("/leaderboard/GetPlayerRank")
    @require_account
    def get_player_rank(account: Account):
        body = leaderboard_body()
        board = str(body.get("LeaderboardName", body.get("StatName", body.get("leaderboard", "default"))))
        row = db.session.get(LeaderboardScore, (account.id, board))
        return jsonify(PlayerId=account.id, Rank=1 if row else 0, Score=row.score if row else 0)

    @app.post("/leaderboard/GetNearbyScores")
    @require_account
    def nearby_scores(account: Account):
        body = leaderboard_body()
        board = str(body.get("LeaderboardName", body.get("StatName", body.get("leaderboard", "default"))))
        rows = db.session.scalars(db.select(LeaderboardScore).where(LeaderboardScore.leaderboard == board).order_by(LeaderboardScore.score.desc()).limit(20)).all()
        return jsonify([{"PlayerId": row.account_id, "Score": row.score, "Rank": index + 1, "IsMe": row.account_id == account.id} for index, row in enumerate(rows)])

    @app.get("/api/avatar/v1/defaultbaseavataritems")
    def default_base_avatar_items():
        return jsonify(DEFAULT_BASE_AVATAR_ITEMS)

    @app.route("/api/PlayerReporting/v1/moderationBlockDetails", methods=["GET", "POST"])
    def moderation_block_details():
        return jsonify(
            ReportCategory=-1,
            Duration=0,
            GameSessionId=0,
            IsBan=False,
            IsHostKick=False,
            IsVoiceModAutoban=False,
            Message=None,
            PlayerIdReporter=None,
            TimeoutStartedAt=None,
        )

    @app.get("/api/playerReputation/v2/bulk")
    def reputation_bulk():
        return jsonify([_default_reputation(account_id) for account_id in _query_ids()])

    @app.get("/api/players/v2/progression/bulk")
    def progression_bulk():
        return jsonify(
            [{"PlayerId": account_id, "Level": 1, "XP": 0} for account_id in _query_ids()]
        )

    @app.get("/playersettings")
    @require_account
    def get_settings(account: Account):
        existing = db.session.scalars(
            db.select(PlayerSetting).where(PlayerSetting.account_id == account.id)
        ).all()
        values = {row.key: row.value for row in existing}
        for key, value in DEFAULT_SETTINGS.items():
            if key not in values:
                db.session.add(PlayerSetting(account_id=account.id, key=key, value=value))
                values[key] = value
        db.session.commit()
        return jsonify([{"PlayerId": account.id, "Key": k, "Value": v} for k, v in values.items()])

    @app.put("/playersettings")
    @require_account
    def put_settings(account: Account):
        body = request.get_json(silent=True) or request.form
        items = body if isinstance(body, list) else [body]
        for item in items:
            key = str(item.get("key", item.get("Key", "")))
            value = str(item.get("value", item.get("Value", "")))
            if key:
                row = db.session.get(PlayerSetting, (account.id, key))
                if row:
                    row.value = value
                else:
                    db.session.add(PlayerSetting(account_id=account.id, key=key, value=value))
        db.session.commit()
        return "", 200

    @app.get("/api/storefronts/v4/balance/<int:currency_type>")
    @require_account
    def balance(account: Account, currency_type: int):
        return jsonify(Balance=account.token_balance, CurrencyType=currency_type)

    @app.get("/api/storefronts/v3/giftdropstore/<storefront_id>")
    def gift_drop_storefront(storefront_id: str):
        storefront = STOREFRONT_FILES.get(storefront_id)
        if storefront is None:
            if not storefront_id.isdigit():
                return "", 404
            return jsonify(StorefrontType=int(storefront_id), StoreItems=[])
        return send_file(storefront, mimetype="application/json")

    @app.post("/api/storefronts/v1/purchase")
    @app.post("/api/storefronts/v2/purchase")
    @app.post("/api/storefronts/v3/purchase")
    @require_account
    def purchase_store_item(account: Account):
        body = request.form if request.form else (request.get_json(silent=True) or {})
        try:
            item_id = int(
                body.get(
                    "PurchasableItemId",
                    body.get("purchasableItemId", body.get("ItemId", body.get("itemId"))),
                )
            )
        except (TypeError, ValueError):
            return jsonify(Success=False, Error="PurchasableItemId is required."), 400

        item = STORE_ITEMS_BY_ID.get(item_id)
        price_entry = next(
            (
                entry
                for entry in (item or {}).get("Prices", [])
                if entry.get("CurrencyType") == 2
            ),
            None,
        )
        if item is None or price_entry is None:
            return jsonify(Success=False, Error="This item is not available for tokens."), 404
        price = int(price_entry.get("Price", 0))
        if price <= 0:
            return jsonify(Success=False, Error="This item has an invalid price."), 400

        expected_price = body.get("ExpectedPrice", body.get("expectedPrice"))
        if expected_price is not None:
            try:
                if int(expected_price) != price:
                    return jsonify(Success=False, Error="The item price has changed."), 409
            except (TypeError, ValueError):
                return jsonify(Success=False, Error="ExpectedPrice must be a number."), 400

        gift = copy.deepcopy(item.get("GiftDrop") or {})
        unique = bool(
            gift.get("Unique")
            or gift.get("AvatarItemDesc")
            or gift.get("EquipmentModificationGuid")
        )
        if unique and db.session.get(OwnedStoreItem, (account.id, item_id)) is not None:
            return jsonify(Success=False, Error="You already own this item."), 409

        debit = db.session.execute(
            db.update(Account)
            .where(Account.id == account.id, Account.token_balance >= price)
            .values(token_balance=Account.token_balance - price)
        )
        if debit.rowcount != 1:
            db.session.rollback()
            return jsonify(Success=False, Error="Not enough tokens."), 400

        transaction_id = str(uuid.uuid4())
        purchase = StorePurchase(
            account_id=account.id,
            purchasable_item_id=item_id,
            price=price,
            gift_drop_json=json.dumps(gift, separators=(",", ":")),
        )
        db.session.add(purchase)
        db.session.add(
            TokenTransaction(
                account_id=account.id,
                amount=-price,
                kind="store_purchase",
                reference=transaction_id,
            )
        )
        if unique:
            db.session.add(OwnedStoreItem(account_id=account.id, purchasable_item_id=item_id))

        consumable = str(gift.get("ConsumableItemDesc") or "")
        if consumable:
            balance_row = db.session.get(ConsumableBalance, (account.id, consumable))
            if balance_row is None:
                default_item = next(
                    (
                        value
                        for value in ALL_UNLOCKS["consumables"]
                        if value.get("ConsumableItemDesc") == consumable
                    ),
                    None,
                )
                balance_row = ConsumableBalance(
                    account_id=account.id,
                    consumable=consumable,
                    quantity=int((default_item or {}).get("Count", 0)),
                )
                db.session.add(balance_row)
            balance_row.quantity += 1

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify(Success=False, Error="The purchase could not be completed."), 409
        db.session.refresh(account)
        return jsonify(
            Success=True,
            Error="",
            TransactionId=transaction_id,
            transactionId=transaction_id,
            Balance=account.token_balance,
            GiftDrop=gift,
        )

    @app.get("/api/catalog/v1/all")
    def purchasable_catalog():
        return jsonify(PURCHASABLE_CATALOG)

    @app.get("/api/storefronts/v1/adcarouselitems")
    def storefront_ad_carousel():
        return jsonify(AD_CAROUSEL_ITEMS)

    @app.get("/api/testcasemanagement/v1/testplans")
    def test_case_plans():
        return jsonify([])

    @app.get("/api/testcasemanagement/v1/testpasssummary")
    def test_case_pass_summary():
        return jsonify([])

    @app.get("/config/LoadingScreenTipData")
    def loading_screen_tips():
        return jsonify(LOADING_SCREEN_TIPS)

    @app.get("/api/challenge/v2/getCurrent")
    def current_challenge():
        return jsonify(
            ChallengeMapId=19,
            CompletedRequired=False,
            StartAt="2026-08-19T21:00:00Z",
            EndAt="2026-09-26T21:00:00Z",
            ServerTime=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            Challenges=[],
            Gift={
                "GiftDropId": 3994,
                "AvatarItemDesc": "",
                "AvatarItemType": 0,
                "ConsumableItemDesc": "",
                "EquipmentPrefabName": "[ShareCamera]",
                "EquipmentModificationGuid": "g5u0weNLmkCLeUXFUVn74Q",
                "StorefrontType": 0,
                "Xp": 0,
                "Level": 0,
                "GiftContext": 0,
                "GiftRarity": 0,
            },
            FallbackGiftName="4-Star Box",
            ChallengeThemeString="",
        )

    @app.get("/api/communityboard/v2/current")
    def community_board():
        return jsonify(COMMUNITY_BOARD)

    @app.get("/api/playerevents/v1/all")
    def player_events_all():
        account = current_account()
        if account is None:
            return jsonify(Created=[], Responses=[])
        created = db.session.scalars(db.select(PlayerEvent).where(PlayerEvent.creator_account_id == account.id).order_by(PlayerEvent.start_at)).all()
        return jsonify(Created=[event_dto(event) for event in created], Responses=[])

    @app.get("/api/PlayerReporting/v1/voteToKickReasons")
    def vote_to_kick_reasons():
        return jsonify(VOTE_TO_KICK_REASONS)

    @app.post("/api/PlayerReporting/v1/hile")
    def report_sink():
        return jsonify(False)

    @app.post("/api/PlayerReporting/v3/create")
    @require_account
    def create_player_report(account: Account):
        body = request.form if request.form else (request.get_json(silent=True) or {})
        raw_target = body.get("PlayerIdReported", body.get("playerIdReported"))
        try:
            target_id = int(raw_target)
        except (TypeError, ValueError):
            return jsonify(success=False, error="PlayerIdReported is required"), 400
        if db.session.get(Account, target_id) is None:
            return jsonify(success=False, error="Reported player was not found"), 400

        def optional_int(name: str):
            try:
                value = int(body.get(name, 0))
                return value if value > 0 else None
            except (TypeError, ValueError):
                return None

        try:
            category = int(body.get("ReportCategory", 0))
        except (TypeError, ValueError):
            category = 0
        report = PlayerReport(
            reporter_account_id=account.id,
            reported_account_id=target_id,
            category=category,
            details=str(body.get("Details", "")).strip()[:2000],
            room_id=optional_int("RoomId"),
            room_instance_type=str(body.get("RoomInstanceType", ""))[:64] or None,
        )
        db.session.add(report)
        db.session.commit()
        return jsonify(success=True, error="")

    @app.post("/api/PlayerReporting/v1/referee")
    def referee_status():
        return jsonify(False)

    @app.get("/api/referee/files")
    def referee_files():
        return jsonify([])

    @app.get("/api/customAvatarItems/v1/isCreationEnabled")
    @app.get("/api/customAvatarItems/v1/isRenderingEnabled")
    def custom_avatar_feature_enabled():
        return jsonify(True)

    @app.get("/api/subscriptionseasons/v1/seasons/current")
    @app.get("/subscription/mine/member")
    @app.get("/announcements/v2/mine/unread")
    @app.get("/announcements/v2/subscription/mine/unread")
    @app.get("/api/announcement/v1/get")
    def builtin_empty_list():
        return jsonify([])

    @app.post("/api/CampusCard/v1/UpdateAndGetSubscription")
    def campus_card_subscription():
        return jsonify({})

    @app.get("/api/roomconsumables/v1/roomConsumable/room/<int:room_id>")
    def room_consumables(room_id: int):
        return jsonify(RoomId=room_id, Consumables=[])

    @app.get("/parentalcontrol/me")
    def parental_control_me():
        return jsonify(IsJunior=False, ParentAccountId=None, Restrictions=[])

    @app.get("/api/influencerpartnerprogram/influencers")
    def influencer_program():
        return jsonify(Results=[], TotalResults=0)

    @app.get("/api/incentivizedreferrals/progress")
    def referral_progress():
        return jsonify(CompletedReferrals=0, Rewards=[], TotalReferrals=0)

    @app.get("/club/<int:club_id>")
    @app.get("/club/<int:club_id>/details")
    @require_account
    def get_club_details(account: Account, club_id: int):
        club = db.session.get(Club, club_id)
        return (jsonify(club_details(club, account.id)), 200) if club else ("", 404)

    @app.get("/club/<int:club_id>/members")
    def club_members(club_id: int):
        memberships = db.session.scalars(
            db.select(ClubMember)
            .where(ClubMember.club_id == club_id)
            .order_by(ClubMember.membership_type.desc(), ClubMember.account_id)
        ).all()
        requested_type = request.args.get("membershipType")
        if requested_type and requested_type.isdigit():
            memberships = [row for row in memberships if row.membership_type == int(requested_type)]
        return jsonify(
            [
                {
                    "ClubId": row.club_id,
                    "AccountId": row.account_id,
                    "MembershipType": row.membership_type,
                    "Account": account_dto(player) if (player := db.session.get(Account, row.account_id)) else None,
                }
                for row in memberships
            ]
        )

    @app.get("/club/<int:club_id>/hasDisabledClubChat")
    def club_chat_disabled(club_id: int):
        return jsonify(db.session.get(Club, club_id) is None)

    @app.route("/club/<int:club_id>/clubhouse", methods=["PUT", "DELETE"])
    @require_account
    def set_clubhouse(account: Account, club_id: int):
        club = db.session.get(Club, club_id)
        member = db.session.get(ClubMember, (club_id, account.id))
        if club is None:
            return "", 404
        if member is None or member.membership_type < 30:
            return "", 403
        if request.method == "DELETE":
            club.clubhouse_room_id = None
        else:
            raw = room_body().get("roomId")
            if not str(raw).isdigit() or db.session.get(Room, int(raw)) is None:
                return jsonify(error="Invalid roomId.", success=False, value=None), 400
            club.clubhouse_room_id = int(raw)
        db.session.commit()
        return jsonify(error="", success=True, value=club_details(club, account.id))

    @app.get("/announcements/club/<int:club_id>")
    def club_announcements(club_id: int):
        rows = db.session.scalars(
            db.select(ClubAnnouncement)
            .where(ClubAnnouncement.club_id == club_id)
            .order_by(ClubAnnouncement.id.desc())
        ).all()
        announcements = [
            {
                "AnnouncementId": row.id,
                "ClubId": row.club_id,
                "AuthorAccountId": row.author_account_id,
                "Title": row.title,
                "Message": row.message,
                "CreatedAt": _iso(row.created_at),
            }
            for row in rows
        ]
        return jsonify(
            Announcements=announcements,
            ClubId=club_id,
            LastAnnouncementId=announcements[0]["AnnouncementId"] if announcements else None,
        )

    @app.post("/announcements/club/<int:club_id>")
    @require_account
    def post_club_announcement(account: Account, club_id: int):
        member = db.session.get(ClubMember, (club_id, account.id))
        if member is None or member.membership_type < 30:
            return "", 403
        body = room_body()
        announcement = ClubAnnouncement(
            club_id=club_id,
            author_account_id=account.id,
            title=str(body.get("title", body.get("Title", ""))),
            message=str(body.get("message", body.get("Message", ""))),
        )
        db.session.add(announcement)
        db.session.commit()
        return jsonify(error="", success=True, value=announcement.id)

    @app.post("/club/<int:club_id>/join")
    @app.post("/club/<int:club_id>/members/requesttojoin")
    @require_account
    def join_club(account: Account, club_id: int):
        club = db.session.get(Club, club_id)
        if club is None:
            return "", 404
        member = db.session.get(ClubMember, (club_id, account.id))
        if member is None:
            member = ClubMember(club_id=club_id, account_id=account.id, membership_type=10)
            db.session.add(member)
            db.session.commit()
        return jsonify(error="", success=True, value=club_details(club, account.id))

    @app.post("/club/<int:club_id>/leave")
    @app.post("/club/<int:club_id>/members/leave")
    @require_account
    def leave_club(account: Account, club_id: int):
        member = db.session.get(ClubMember, (club_id, account.id))
        if member and member.membership_type < 100:
            db.session.delete(member)
            db.session.commit()
        return jsonify(error="", success=True, value=None)

    @app.post("/club/<int:club_id>/members/invite")
    @require_account
    def invite_club_members(account: Account, club_id: int):
        caller = db.session.get(ClubMember, (club_id, account.id))
        if caller is None or caller.membership_type < 20:
            return "", 403
        body = request.get_json(silent=True) or room_body()
        targets = body.get("AccountIds", body.get("accountIds", body.get("accountId", body.get("id", []))))
        if not isinstance(targets, list):
            targets = [targets]
        added = []
        for raw in targets:
            try:
                target_id = int(raw)
            except (TypeError, ValueError):
                continue
            if db.session.get(Account, target_id) is None or db.session.get(ClubMember, (club_id, target_id)):
                continue
            try:
                membership_type = int(body.get("membershipType", 10) or 10)
            except (TypeError, ValueError):
                membership_type = 10
            if membership_type not in {10, 20, 30}:
                membership_type = 10
            db.session.add(ClubMember(club_id=club_id, account_id=target_id, membership_type=membership_type))
            added.append(target_id)
        db.session.commit()
        return jsonify(error="", success=True, value=added)

    @app.get("/purchase/v1/hasspentmoney")
    def has_spent_money():
        return jsonify(False)

    @app.post("/purchase/v1/initiatepurchase")
    def initiate_purchase():
        return jsonify(transactionId="recadoodle-no-charge")

    @app.route("/purchase/v1/cleanuppending", methods=["GET", "POST"])
    @app.get("/purchasecampaign/allcurrent/v2")
    @app.get("/reminder/currentTokenBundles/v2")
    def empty_purchase_state():
        return jsonify([])

    empty_gets = [
        "/api/checklist/v1/current",
        "/api/itemWishlists/v1/wishlist/me",
        "/api/avatar/v2/gifts",
        "/api/roomcurrencies/v1/currencies",
        "/api/roomcurrencies/v1/getAllBalances",
        "/api/gamerewards/v1/pending",
        "/api/roomkeys/v1/mine",
        "/rooms/requiring/developer",
        "/rooms/requiring/rrplus",
    ]
    for index, path in enumerate(empty_gets):
        app.add_url_rule(path, f"empty_{index}", lambda: jsonify([]), methods=["GET"])
