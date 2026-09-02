"""Read-only protocol catalogs and discovery constants.

Keeping archived data loading here makes route modules about request handling rather
than filesystem layout. Catalogs are loaded once when the application starts.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

PACKAGE_DIR = Path(__file__).parent
DATA_DIR = PACKAGE_DIR / "data"
ROOM_IMAGE_DIR = PACKAGE_DIR / "static" / "room-thumbnails"


def _load(name: str, *, encoding: str = "utf-8"):
    return json.loads((DATA_DIR / name).read_text(encoding=encoding))


API_CONFIG_V2 = _load("api-config-v2.json")
GAME_CONFIGS_2023 = _load("gameconfigs-v1-all.json")
ALL_UNLOCKS = _load("all-unlocks.json")
MAKER_PEN_SKINS = _load("maker-pen-skins.json")
_equipment_guids = {item["ModificationGuid"] for item in ALL_UNLOCKS["equipment"]}
for _skin in MAKER_PEN_SKINS:
    if _skin["ModificationGuid"] not in _equipment_guids:
        ALL_UNLOCKS["equipment"].append(copy.deepcopy(_skin))
        _equipment_guids.add(_skin["ModificationGuid"])
FULL_AVATAR_ITEMS = _load("catalog-avatar-items.json", encoding="utf-8-sig")
MY_PROGRESS = _load("my-progress.json", encoding="utf-8-sig")
DEFAULT_BASE_AVATAR_ITEMS = _load("default-base-avatar-items.json", encoding="utf-8-sig")
DEFAULT_AVATAR = _load("default-avatar.json")
PURCHASABLE_CATALOG = _load("catalog-v1-all.json")
AD_CAROUSEL_ITEMS = _load("ad-carousel-items.json")
STOREFRONT_FILES = {
    path.stem.removeprefix("storefront-sf"): path for path in DATA_DIR.glob("storefront-sf*.json")
}


def _with_storefront_avatar_items(items: list[dict]) -> list[dict]:
    result = list(items)
    known = {str(item.get("AvatarItemDesc", "")) for item in result}
    for path in STOREFRONT_FILES.values():
        storefront = json.loads(path.read_text(encoding="utf-8-sig"))
        for store_item in storefront.get("StoreItems", []):
            gift = store_item.get("GiftDrop") or {}
            description = str(gift.get("AvatarItemDesc") or "")
            if description and description not in known:
                result.append(copy.deepcopy(gift))
                known.add(description)
    return result


FULL_AVATAR_ITEMS = _with_storefront_avatar_items(FULL_AVATAR_ITEMS)
BUILTIN_ROOMS = _load("rooms.json", encoding="utf-8-sig")
BUILTIN_ROOMS_BY_ID = {int(room["RoomId"]): room for room in BUILTIN_ROOMS}

LOADING_SCREEN_TIPS = [
    {
        "Name": "recadoodle-welcome",
        "Title": "Welcome to Recadoodle",
        "Message": "Welcome to your community server.",
        "RoomNames": [],
        "Context": 0,
        "InputType": 0,
        "Visibility": 1,
        "AllowCycling": True,
        "RestrictToNewUsers": False,
        "ImageName": "tip.jpg",
        "PlatformMask": 175,
        "CreatedAt": "2023-04-18T00:00:00Z",
    },
    {
        "Name": "recadoodle-style",
        "Title": "Find Your Style",
        "Message": "Personalize your outfit and appearance in your Dorm Room.",
        "RoomNames": [],
        "Context": 0,
        "InputType": 0,
        "Visibility": 0,
        "AllowCycling": True,
        "RestrictToNewUsers": False,
        "ImageName": "tip.jpg",
        "PlatformMask": 175,
        "CreatedAt": "2023-04-18T00:00:00Z",
    },
]

COMMUNITY_BOARD = {
    "FeaturedPlayer": {"Id": 1, "TitleOverride": "", "UrlOverride": None},
    "FeaturedRoomGroup": {"FeaturedRoomGroupId": 2, "Name": "Featured Rooms", "Rooms": []},
    "CurrentAnnouncement": {
        "Message": "Welcome to Recadoodle",
        "MoreInfoUrl": "",
    },
    "InstagramImages": [],
    "Videos": [],
}

VOTE_TO_KICK_REASONS = [
    {"Reason": "Discriminatory language", "ReportCategory": 102},
    {"Reason": "Discriminatory behavior", "ReportCategory": 102},
    {"Reason": "Threats or encouraging suicide", "ReportCategory": 102},
    {"Reason": "Toxic behavior", "ReportCategory": 102},
    {"Reason": "Sexual behavior in public", "ReportCategory": 101},
    {"Reason": "Sexual language in public", "ReportCategory": 101},
    {"Reason": "Non-consensual sexual behavior", "ReportCategory": 101},
    {"Reason": "Player in walls or floor", "ReportCategory": 103},
    {"Reason": "Friendly fire", "ReportCategory": 103},
    {"Reason": "Microphone spam", "ReportCategory": 103},
    {"Reason": "Abusing bugs or exploits", "ReportCategory": 103},
    {"Reason": "Spawn camping", "ReportCategory": 103},
    {"Reason": "Inactive in games (AFK)", "ReportCategory": 6},
    {"Reason": "Prefab swapping", "ReportCategory": 6},
    {"Reason": "Not following game rules", "ReportCategory": 6},
]

PUBLISHED_CONFIGS = {
    "1b057e6e-979d-4f30-8856-a386f77c90da",
    "RRPlusConfig_v3.json",
    "SkuConfig_v1.json",
}

SERVICE_SUBDOMAINS = {
    "Accounts": "accounts",
    "AI": "ai",
    "API": "api",
    "Auth": "auth",
    "BugReporting": "bugreporting",
    "Cards": "cards",
    "CDN": "cdn",
    "Chat": "chat",
    "Clubs": "clubs",
    "CMS": "cms",
    "Commerce": "commerce",
    "Data": "data",
    "DataCollection": "datacollection",
    "Discovery": "discovery",
    "Econ": "econ",
    "GameLogs": "gamelogs",
    "Geo": "geo",
    "Images": "img",
    "Leaderboard": "leaderboard",
    "Link": "link",
    "Lists": "lists",
    "Matchmaking": "match",
    "Moderation": "api",
    "Notifications": "notify",
    "PlatformNotifications": "platformnotifications",
    "PlayerSettings": "playersettings",
    "RoomComments": "roomcomments",
    "RoomieIntegrations": "roomieintegrations",
    "Rooms": "rooms",
    "Storage": "storage",
    "Strings": "strings",
    "StringsCDN": "strings-cdn",
    "Studio": "studio",
    "Thorn": "thorn",
    "Videos": "videos",
    "WWW": "www",
}

DEFAULT_SETTINGS = {
    "PlayerSessionCount": "0",
    "AvoidJuniors": "False",
    "TelemetryEnabled": "False",
}
