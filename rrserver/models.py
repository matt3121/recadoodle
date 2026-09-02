from __future__ import annotations

from datetime import UTC, datetime

from .extensions import db


def utcnow() -> datetime:
    return datetime.now(UTC)


class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(32), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(64), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False, default="")
    email = db.Column(db.String(255), nullable=False, default="")
    bio = db.Column(db.Text, nullable=False, default="")
    profile_image = db.Column(db.String(255), nullable=False, default="")
    is_junior = db.Column(db.Boolean, nullable=False, default=False)
    platforms = db.Column(db.Integer, nullable=False, default=0)
    personal_pronouns = db.Column(db.Integer, nullable=False, default=0)
    identity_flags = db.Column(db.Integer, nullable=False, default=0)
    is_developer = db.Column(db.Boolean, nullable=False, default=False)
    is_moderator = db.Column(db.Boolean, nullable=False, default=False)
    token_balance = db.Column(db.Integer, nullable=False, default=10000)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class PlatformAccountLink(db.Model):
    """Account-picker association only; never proof of authentication."""

    platform = db.Column(db.String(16), primary_key=True)
    platform_id = db.Column(db.String(128), primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), primary_key=True)


class RefreshToken(db.Model):
    token = db.Column(db.String(128), primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class PlayerSetting(db.Model):
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), primary_key=True)
    key = db.Column(db.String(128), primary_key=True)
    value = db.Column(db.Text, nullable=False, default="")


class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=False, default="")
    scene = db.Column(db.String(100), nullable=False)
    max_players = db.Column(db.Integer, nullable=False, default=40)
    creator_account_id = db.Column(db.Integer, nullable=False, default=1)


class RoomProfile(db.Model):
    room_id = db.Column(db.Integer, db.ForeignKey("room.id"), primary_key=True)
    image_name = db.Column(db.String(255), nullable=False, default="")
    accessibility = db.Column(db.Integer, nullable=False, default=0)
    publish_state = db.Column(db.Integer, nullable=False, default=0)
    cloning_allowed = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    published_at = db.Column(db.DateTime(timezone=True), nullable=True)


class SubRoom(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("room.id"), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False, default="Home")
    scene = db.Column(db.String(100), nullable=False)
    max_players = db.Column(db.Integer, nullable=False, default=40)
    accessibility = db.Column(db.Integer, nullable=False, default=0)
    current_save_id = db.Column(db.Integer, nullable=True)
    staged_save_id = db.Column(db.Integer, nullable=True)


class RoomSave(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sub_room_id = db.Column(db.Integer, db.ForeignKey("sub_room.id"), nullable=False, index=True)
    saved_by_account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    data = db.Column(db.Text, nullable=False, default="")
    description = db.Column(db.Text, nullable=False, default="")
    unity_asset_id = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class RoomRole(db.Model):
    room_id = db.Column(db.Integer, db.ForeignKey("room.id"), primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), primary_key=True)
    role = db.Column(db.Integer, nullable=False, default=0)
    changed_by_account_id = db.Column(db.Integer, nullable=True)


class RoomBan(db.Model):
    room_id = db.Column(db.Integer, db.ForeignKey("room.id"), primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), primary_key=True)
    ban_mask = db.Column(db.Integer, nullable=False, default=0)
    banned_by_account_id = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class RoomSetting(db.Model):
    room_id = db.Column(db.Integer, db.ForeignKey("room.id"), primary_key=True)
    warning_mask = db.Column(db.Integer, nullable=False, default=0)
    custom_warning = db.Column(db.Text, nullable=False, default="")
    tags_json = db.Column(db.Text, nullable=False, default="[]")
    restrictions_json = db.Column(db.Text, nullable=False, default="{}")
    load_screens_json = db.Column(db.Text, nullable=False, default="[]")


class SubRoomPermission(db.Model):
    sub_room_id = db.Column(db.Integer, db.ForeignKey("sub_room.id"), primary_key=True)
    permission = db.Column(db.String(128), primary_key=True)
    role = db.Column(db.Integer, primary_key=True)
    value = db.Column(db.String(255), nullable=False, default="True")


class CircuitValue(db.Model):
    room_id = db.Column(db.Integer, db.ForeignKey("room.id"), primary_key=True)
    key = db.Column(db.String(255), primary_key=True)
    account_id = db.Column(db.Integer, primary_key=True, default=0)
    value_json = db.Column(db.Text, nullable=False, default="null")
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class Presence(db.Model):
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("room.id"), nullable=True)
    room_instance_id = db.Column(db.Integer, nullable=True)
    status_visibility = db.Column(db.Integer, nullable=False, default=0)
    device_class = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class RoomInstanceState(db.Model):
    room_instance_id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("room.id"), nullable=False, index=True)
    in_progress = db.Column(db.Boolean, nullable=False, default=False)
    is_private = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class RoomComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("room.id"), nullable=False, index=True)
    sub_room_id = db.Column(db.Integer, nullable=False, index=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    message = db.Column(db.Text, nullable=False)
    style = db.Column(db.Integer, nullable=False, default=0)
    position_x = db.Column(db.Float, nullable=False, default=0.0)
    position_y = db.Column(db.Float, nullable=False, default=0.0)
    position_z = db.Column(db.Float, nullable=False, default=0.0)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class AvatarState(db.Model):
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), primary_key=True)
    data = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class SavedOutfit(db.Model):
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), primary_key=True)
    slot = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class Relationship(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False, index=True)
    target_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False, index=True)
    relationship_type = db.Column(db.Integer, nullable=False, default=0)
    requester_favorited = db.Column(db.Boolean, nullable=False, default=False)
    requester_ignored = db.Column(db.Boolean, nullable=False, default=False)
    requester_muted = db.Column(db.Boolean, nullable=False, default=False)
    target_favorited = db.Column(db.Boolean, nullable=False, default=False)
    target_ignored = db.Column(db.Boolean, nullable=False, default=False)
    target_muted = db.Column(db.Boolean, nullable=False, default=False)
    __table_args__ = (db.UniqueConstraint("requester_id", "target_id"),)


class RoomInteraction(db.Model):
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("room.id"), primary_key=True)
    cheered = db.Column(db.Boolean, nullable=False, default=False)
    favorited = db.Column(db.Boolean, nullable=False, default=False)
    last_visited_at = db.Column(db.DateTime(timezone=True), nullable=True)


class RoomInvite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    from_player_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False, index=True)
    to_player_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False, index=True)
    room_id = db.Column(db.Integer, db.ForeignKey("room.id"), nullable=True)
    room_instance_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class PlayerMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    from_player_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    to_player_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False, index=True)
    message_type = db.Column(db.Integer, nullable=False, default=0)
    data = db.Column(db.Text, nullable=False, default="")
    room_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class ChatThread(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class ChatThreadMember(db.Model):
    thread_id = db.Column(db.Integer, db.ForeignKey("chat_thread.id"), primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), primary_key=True)
    last_read_message_id = db.Column(db.Integer, nullable=False, default=0)
    is_favorited = db.Column(db.Boolean, nullable=False, default=False)
    snoozed_until = db.Column(db.DateTime(timezone=True), nullable=True)


class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    thread_id = db.Column(db.Integer, db.ForeignKey("chat_thread.id"), nullable=False, index=True)
    sender_account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    contents = db.Column(db.Text, nullable=False)
    moderation_state = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class Club(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40), nullable=False, index=True)
    description = db.Column(db.Text, nullable=False, default="")
    category = db.Column(db.String(40), nullable=False, default="Social")
    visibility = db.Column(db.Integer, nullable=False, default=1)
    joinability = db.Column(db.Integer, nullable=False, default=0)
    allow_juniors = db.Column(db.Boolean, nullable=False, default=True)
    main_image_name = db.Column(db.String(255), nullable=False, default="DefaultImgPurple")
    clubhouse_room_id = db.Column(db.Integer, nullable=True)
    creator_account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class ClubMember(db.Model):
    club_id = db.Column(db.Integer, db.ForeignKey("club.id"), primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), primary_key=True)
    membership_type = db.Column(db.Integer, nullable=False, default=10)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class HomeClub(db.Model):
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("club.id"), nullable=False)


class LeaderboardScore(db.Model):
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), primary_key=True)
    leaderboard = db.Column(db.String(128), primary_key=True)
    score = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class PlayerImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False, index=True)
    image_name = db.Column(db.String(255), nullable=False, default="")
    room_id = db.Column(db.Integer, nullable=True)
    caption = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class PlayerEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    creator_account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey("room.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    start_at = db.Column(db.DateTime(timezone=True), nullable=False)
    end_at = db.Column(db.DateTime(timezone=True), nullable=False)
    capacity = db.Column(db.Integer, nullable=False, default=40)
    tags_json = db.Column(db.Text, nullable=False, default="[]")


class PlayerEventResponse(db.Model):
    event_id = db.Column(db.Integer, db.ForeignKey("player_event.id"), primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), primary_key=True)
    response_type = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class ClubAnnouncement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("club.id"), nullable=False, index=True)
    author_account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    title = db.Column(db.String(120), nullable=False, default="")
    message = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class ConsumableBalance(db.Model):
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), primary_key=True)
    consumable = db.Column(db.String(255), primary_key=True)
    quantity = db.Column(db.Integer, nullable=False, default=0)


class EquipmentPreference(db.Model):
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), primary_key=True)
    modification_guid = db.Column(db.String(255), primary_key=True)
    favorited = db.Column(db.Boolean, nullable=False, default=False)


class ReceivedGift(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False, index=True)
    data_json = db.Column(db.Text, nullable=False, default="{}")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class PlayerReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reporter_account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    reported_account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False, index=True)
    category = db.Column(db.Integer, nullable=False, default=0)
    details = db.Column(db.Text, nullable=False, default="")
    room_id = db.Column(db.Integer, nullable=True)
    room_instance_type = db.Column(db.String(64), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="open", index=True)
    reviewed_by_account_id = db.Column(db.Integer, nullable=True)
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
