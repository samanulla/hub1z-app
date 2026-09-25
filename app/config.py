"""Environment-based configuration for hub1z."""
from __future__ import annotations

import os
from datetime import timedelta


def _bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


class BaseConfig:
    APP_NAME = os.getenv("APP_NAME", "hub1z")
    APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5000")
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")

    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://coworkhub:coworkhub@localhost:5432/coworkhub",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 300}

    WTF_CSRF_TIME_LIMIT = 60 * 60 * 4
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Storage
    STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local").lower()
    LOCAL_STORAGE_DIR = os.getenv("LOCAL_STORAGE_DIR", "./var/uploads")
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET", "")
    AWS_S3_PLATFORM_BUCKET = os.getenv("AWS_S3_PLATFORM_BUCKET") or os.getenv("AWS_S3_BUCKET", "")
    AWS_S3_OPERATOR_BUCKET = os.getenv("AWS_S3_OPERATOR_BUCKET") or os.getenv("AWS_S3_BUCKET", "")
    AWS_S3_PREFIX = os.getenv("AWS_S3_PREFIX", "documents/")
    AWS_S3_URL_TTL = int(os.getenv("AWS_S3_URL_TTL", "3600"))
    AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
    AZURE_STORAGE_CONTAINER = os.getenv("AZURE_STORAGE_CONTAINER", "documents")

    # Mail
    MAIL_SERVER = os.getenv("MAIL_SERVER", "localhost")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "25"))
    MAIL_USE_TLS = _bool("MAIL_USE_TLS", False)
    MAIL_USERNAME = os.getenv("MAIL_USERNAME") or None
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD") or None
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "no-reply@hub1z.com")
    MAIL_SUPPRESS_SEND = _bool("MAIL_SUPPRESS_SEND", False)

    # Booking policy
    BOOKING_MIN_ADVANCE_MINUTES = int(os.getenv("BOOKING_MIN_ADVANCE_MINUTES", "15"))
    BOOKING_MAX_ADVANCE_DAYS = int(os.getenv("BOOKING_MAX_ADVANCE_DAYS", "60"))
    BOOKING_CANCEL_WINDOW_MINUTES = int(os.getenv("BOOKING_CANCEL_WINDOW_MINUTES", "60"))
    DEFAULT_ROOM_SLOT_MINUTES = int(os.getenv("DEFAULT_ROOM_SLOT_MINUTES", "30"))

    # Bootstrap admin — this is the sample TENANT's admin (seed-demo), not the
    # platform super admin. It must use a tenant domain, never hub1z.com.
    BOOTSTRAP_ADMIN_EMAIL = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "admin@adyarspace.com")
    BOOTSTRAP_ADMIN_PASSWORD = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "ChangeMe123!")

    # Multi-tenancy
    DEPLOY_MODE = os.getenv("DEPLOY_MODE", "shared").lower()  # 'shared' | 'dedicated'
    TENANT_ID = os.getenv("TENANT_ID")  # only used when DEPLOY_MODE=dedicated
    PLATFORM_BASE_DOMAIN = os.getenv("PLATFORM_BASE_DOMAIN", "hub1z.com")
    TENANT_TRIAL_DAYS = int(os.getenv("TENANT_TRIAL_DAYS", "14"))


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    TEMPLATES_AUTO_RELOAD = True


class ProductionConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    PREFERRED_URL_SCHEME = "https"


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    MAIL_SUPPRESS_SEND = True


def get_config() -> type[BaseConfig]:
    env = os.getenv("FLASK_ENV", "development").lower()
    if env == "production":
        return ProductionConfig
    if env == "testing":
        return TestingConfig
    return DevelopmentConfig
