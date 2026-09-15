"""Database models."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite gives naive datetimes back; normalise everything to aware UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="member")  # admin | member
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    timezone: Mapped[str] = mapped_column(String(64), default="America/Guayaquil")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class LinkedInAccount(Base):
    """One LinkedIn identity the app can send invitations from."""

    __tablename__ = "linkedin_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    label: Mapped[str] = mapped_column(String(120))
    linkedin_name: Mapped[str] = mapped_column(String(120), default="")
    # Fernet-encrypted JSON: {"li_at": ..., "JSESSIONID": ..., "li_a": ...}
    cookies_encrypted: Mapped[str] = mapped_column(Text, default="")
    user_agent: Mapped[str] = mapped_column(Text, default="")

    timezone: Mapped[str] = mapped_column(String(64), default="America/Guayaquil")
    daily_limit: Mapped[int] = mapped_column(Integer, default=20)
    weekly_limit: Mapped[int] = mapped_column(Integer, default=100)
    window_start_hour: Mapped[int] = mapped_column(Integer, default=9)
    window_end_hour: Mapped[int] = mapped_column(Integer, default=18)
    skip_weekends: Mapped[bool] = mapped_column(Boolean, default=True)
    min_delay_seconds: Mapped[int] = mapped_column(Integer, default=90)
    max_delay_seconds: Mapped[int] = mapped_column(Integer, default=300)

    # active | paused | needs_reauth | cooldown
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    status_detail: Mapped[str] = mapped_column(Text, default="")
    next_send_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    owner: Mapped[User] = relationship()


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("linkedin_accounts.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    # running | paused | completed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    source_type: Mapped[str] = mapped_column(String(20), default="csv")  # csv | sheet
    source_name: Mapped[str] = mapped_column(Text, default="")
    sheet_url: Mapped[str] = mapped_column(Text, default="")
    sheet_tab: Mapped[str] = mapped_column(String(120), default="")
    result_column: Mapped[str] = mapped_column(String(120), default="Result")
    write_back: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    account: Mapped[LinkedInAccount] = relationship()
    owner: Mapped[User] = relationship()


class Invitation(Base):
    """One queued connection request."""

    __tablename__ = "invitations"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("linkedin_accounts.id"), index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    profile_id: Mapped[str] = mapped_column(String(120), default="")  # ACoAA...
    raw_value: Mapped[str] = mapped_column(Text, default="")
    full_name: Mapped[str] = mapped_column(String(160), default="")
    company: Mapped[str] = mapped_column(String(160), default="")
    title: Mapped[str] = mapped_column(String(200), default="")
    message: Mapped[str] = mapped_column(Text, default="")

    # pending | sent | failed | skipped
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    http_status: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str] = mapped_column(String(80), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    sheet_row: Mapped[int | None] = mapped_column(Integer)
    sheet_synced: Mapped[bool] = mapped_column(Boolean, default=True)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    campaign: Mapped[Campaign] = relationship()


Index("ix_invitations_account_status", Invitation.account_id, Invitation.status)
Index("ix_invitations_campaign_status", Invitation.campaign_id, Invitation.status)
Index("ix_invitations_owner_sent", Invitation.owner_id, Invitation.sent_at)
