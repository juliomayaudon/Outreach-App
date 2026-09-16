"""Application settings, all driven by environment variables (Railway friendly)."""
from __future__ import annotations

import functools
import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- core -------------------------------------------------------------
    app_name: str = "Outreach"
    # Railway injects DATABASE_URL when you attach a Postgres service.
    database_url: str = "sqlite:///./outreach.db"
    # Used to sign session cookies AND to derive the key that encrypts the
    # LinkedIn cookies at rest. Changing it logs everyone out and makes the
    # stored LinkedIn tokens unreadable, so set it once and keep it.
    app_secret: str = "dev-secret-change-me"
    session_days: int = 14
    cookie_secure: bool = True
    default_timezone: str = "America/Guayaquil"

    # --- bootstrap admin --------------------------------------------------
    # Created on first boot if no user exists yet.
    admin_email: str = "admin@example.com"
    admin_password: str = ""

    # --- worker -----------------------------------------------------------
    run_worker: bool = True
    worker_poll_seconds: int = 15
    # Safety ceiling applied on top of whatever each account is configured
    # with. LinkedIn restricts accounts that invite aggressively.
    max_daily_limit: int = 80
    max_weekly_limit: int = 200

    # --- google sheets ----------------------------------------------------
    # Paste the whole service-account JSON here (Railway variable).
    google_service_account_json: str = ""

    # --- google sign-in ---------------------------------------------------
    # From an OAuth client of type "Web application" in Google Cloud.
    google_client_id: str = ""
    google_client_secret: str = ""
    # Only addresses in this Workspace domain may sign in. Empty allows any
    # Google account, which is almost never what you want here.
    google_allowed_domain: str = "kalungi.com"
    # Where Google sends the browser back. Left empty it is derived from
    # RAILWAY_PUBLIC_DOMAIN, because the scheme behind Railway's proxy cannot
    # be read off the request reliably and the URI has to match exactly.
    public_base_url: str = ""

    # --- frontend ---------------------------------------------------------
    cors_origins: str = ""

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url
        # Railway hands out postgres:// or postgresql://; SQLAlchemy 2 + psycopg3
        # needs the driver spelled out.
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://") :]
        return url

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def base_url(self) -> str:
        """The app's own public origin, without a trailing slash."""
        if self.public_base_url:
            return self.public_base_url.rstrip("/")
        domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
        return f"https://{domain}" if domain else ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()
