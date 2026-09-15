"""Request/response models."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str
    is_active: bool
    timezone: str

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    email: EmailStr
    name: str = ""
    password: str = Field(min_length=8)
    role: str = "member"


class UserUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8)
    timezone: str | None = None


class AccountLimits(BaseModel):
    daily_limit: int = Field(default=20, ge=1, le=500)
    weekly_limit: int = Field(default=100, ge=1, le=1000)
    window_start_hour: int = Field(default=9, ge=0, le=23)
    window_end_hour: int = Field(default=18, ge=0, le=23)
    skip_weekends: bool = True
    min_delay_seconds: int = Field(default=90, ge=10, le=7200)
    max_delay_seconds: int = Field(default=300, ge=10, le=7200)
    timezone: str = "America/Guayaquil"


class AccountCreate(AccountLimits):
    label: str = Field(min_length=1, max_length=120)
    tokens: str  # the dict copied from the browser / notebook


class AccountUpdate(BaseModel):
    label: str | None = None
    tokens: str | None = None
    daily_limit: int | None = Field(default=None, ge=1, le=500)
    weekly_limit: int | None = Field(default=None, ge=1, le=1000)
    window_start_hour: int | None = Field(default=None, ge=0, le=23)
    window_end_hour: int | None = Field(default=None, ge=0, le=23)
    skip_weekends: bool | None = None
    min_delay_seconds: int | None = Field(default=None, ge=10, le=7200)
    max_delay_seconds: int | None = Field(default=None, ge=10, le=7200)
    timezone: str | None = None
    status: str | None = None  # active | paused


class AccountOut(BaseModel):
    id: int
    label: str
    linkedin_name: str
    owner_id: int
    owner_name: str = ""
    status: str
    status_detail: str
    timezone: str
    daily_limit: int
    weekly_limit: int
    window_start_hour: int
    window_end_hour: int
    skip_weekends: bool
    min_delay_seconds: int
    max_delay_seconds: int
    next_send_at: datetime | None = None
    last_checked_at: datetime | None = None
    sent_today: int = 0
    sent_this_week: int = 0
    daily_remaining: int = 0
    weekly_remaining: int = 0
    pending: int = 0
    in_window: bool = True


class ColumnMapping(BaseModel):
    vmid: str
    full_name: str = ""
    first_name: str = ""
    company: str = ""
    title: str = ""
    message: str = ""


class SheetPreviewIn(BaseModel):
    url: str
    tab: str = ""


class PreviewOut(BaseModel):
    headers: list[str]
    sample: list[dict]
    total_rows: int
    suggested_mapping: dict
    tabs: list[str] = []


class CampaignSheetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    account_id: int
    url: str
    tab: str = ""
    mapping: ColumnMapping
    note_template: str = ""
    result_column: str = "Result"
    write_back: bool = True
    start_now: bool = True


class CampaignOut(BaseModel):
    id: int
    name: str
    status: str
    account_id: int
    account_label: str = ""
    owner_id: int
    owner_name: str = ""
    source_type: str
    source_name: str
    created_at: datetime
    completed_at: datetime | None = None
    total: int = 0
    pending: int = 0
    sent: int = 0
    failed: int = 0
    skipped: int = 0


class InvitationOut(BaseModel):
    id: int
    profile_id: str
    raw_value: str
    full_name: str
    company: str
    title: str
    message: str
    status: str
    error_code: str
    error_message: str
    http_status: int | None
    attempts: int
    sheet_row: int | None
    sent_at: datetime | None

    model_config = {"from_attributes": True}


class CampaignCreateResult(BaseModel):
    campaign: CampaignOut
    queued: int
    skipped: int
    skipped_examples: list[dict] = []
