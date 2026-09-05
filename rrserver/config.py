from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


def _origins(name: str) -> tuple[str, ...]:
    return tuple(value.strip() for value in os.getenv(name, "").split(",") if value.strip())


class Config:
    RECNET_DOMAIN = os.getenv("RECNET_DOMAIN", "localhost:5000")
    SINGLE_HOST_MODE = _bool("SINGLE_HOST_MODE")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///recnet.sqlite3")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET = os.getenv("JWT_SECRET", "replace-me-with-a-long-random-value")
    TOKEN_TTL_SECONDS = int(os.getenv("TOKEN_TTL_SECONDS", "604800"))
    REFRESH_TOKEN_TTL_SECONDS = int(os.getenv("REFRESH_TOKEN_TTL_SECONDS", "2592000"))
    STARTING_TOKENS = int(os.getenv("STARTING_TOKENS", "10000"))
    GAME_REWARD_TOKENS = int(os.getenv("GAME_REWARD_TOKENS", "100"))
    DAILY_GAME_REWARD_LIMIT = int(os.getenv("DAILY_GAME_REWARD_LIMIT", "1000"))
    PHOTON_REALTIME_APP_ID = os.getenv("PHOTON_REALTIME_APP_ID", "")
    PHOTON_VOICE_APP_ID = os.getenv("PHOTON_VOICE_APP_ID", "")
    PHOTON_CHAT_APP_ID = os.getenv("PHOTON_CHAT_APP_ID", "")
    PHOTON_REGION = os.getenv("PHOTON_REGION", "us")
    TRUST_CLOUDFLARE_PROXY = _bool("TRUST_CLOUDFLARE_PROXY")
    TRUSTED_HOSTS = _origins("TRUSTED_HOSTS") or None
    CORS_ALLOWED_ORIGINS = _origins("CORS_ALLOWED_ORIGINS")
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(64 * 1024 * 1024)))
    MAX_FORM_MEMORY_SIZE = int(os.getenv("MAX_FORM_MEMORY_SIZE", str(2 * 1024 * 1024)))
    MAX_FORM_PARTS = int(os.getenv("MAX_FORM_PARTS", "100"))
    MIN_PASSWORD_LENGTH = int(os.getenv("MIN_PASSWORD_LENGTH", "12"))
    ALLOW_PASSWORDLESS_ACCOUNTS = _bool("ALLOW_PASSWORDLESS_ACCOUNTS")
    CREATE_DEVELOPER_ACCOUNTS_ON_LOGIN = _bool("CREATE_DEVELOPER_ACCOUNTS_ON_LOGIN")
    RATE_LIMIT_ENABLED = _bool("RATE_LIMIT_ENABLED", True)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool(
        "SESSION_COOKIE_SECURE", not RECNET_DOMAIN.startswith(("localhost", "127."))
    )
