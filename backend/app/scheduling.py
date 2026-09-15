"""Send windows and quota arithmetic.

Pure functions so the pacing rules can be tested without a LinkedIn account.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Invitation, LinkedInAccount, as_utc


def account_zone(account: LinkedInAccount) -> ZoneInfo:
    try:
        return ZoneInfo(account.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def to_local(account: LinkedInAccount, moment: datetime) -> datetime:
    return as_utc(moment).astimezone(account_zone(account))


def is_working_day(account: LinkedInAccount, local: datetime) -> bool:
    return not (account.skip_weekends and local.weekday() >= 5)


def within_window(account: LinkedInAccount, moment: datetime) -> bool:
    local = to_local(account, moment)
    if not is_working_day(account, local):
        return False
    start, end = account.window_start_hour, account.window_end_hour
    if start == end:  # 0-0 means "any time"
        return True
    if start < end:
        return start <= local.hour < end
    # window that crosses midnight (e.g. 22 -> 6)
    return local.hour >= start or local.hour < end


def next_window_start(account: LinkedInAccount, moment: datetime) -> datetime:
    """First instant at or after `moment` when this account may send again."""
    local = to_local(account, moment)
    zone = account_zone(account)
    start = account.window_start_hour
    end = account.window_end_hour

    candidate = local
    for _ in range(14):  # at most two weeks ahead, always terminates
        if is_working_day(account, candidate):
            if start == end:
                return candidate.astimezone(timezone.utc)
            day_start = datetime.combine(candidate.date(), time(hour=start), tzinfo=zone)
            if candidate <= day_start:
                return day_start.astimezone(timezone.utc)
            if within_window(account, candidate.astimezone(timezone.utc)):
                return candidate.astimezone(timezone.utc)
        # move to the start of the next day
        candidate = datetime.combine(
            candidate.date() + timedelta(days=1), time(hour=0), tzinfo=zone
        )
    return (local + timedelta(days=1)).astimezone(timezone.utc)


def local_day_bounds(account: LinkedInAccount, moment: datetime) -> tuple[datetime, datetime]:
    local = to_local(account, moment)
    zone = account_zone(account)
    start = datetime.combine(local.date(), time(0), tzinfo=zone)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def local_week_bounds(account: LinkedInAccount, moment: datetime) -> tuple[datetime, datetime]:
    local = to_local(account, moment)
    zone = account_zone(account)
    monday = local.date() - timedelta(days=local.weekday())
    start = datetime.combine(monday, time(0), tzinfo=zone)
    return start.astimezone(timezone.utc), (start + timedelta(days=7)).astimezone(timezone.utc)


def sent_between(db: Session, account_id: int, start: datetime, end: datetime) -> int:
    return int(
        db.scalar(
            select(func.count(Invitation.id)).where(
                Invitation.account_id == account_id,
                Invitation.status == "sent",
                Invitation.sent_at >= start,
                Invitation.sent_at < end,
            )
        )
        or 0
    )


def quota_state(db: Session, account: LinkedInAccount, moment: datetime) -> dict:
    day_start, day_end = local_day_bounds(account, moment)
    week_start, week_end = local_week_bounds(account, moment)
    today = sent_between(db, account.id, day_start, day_end)
    this_week = sent_between(db, account.id, week_start, week_end)
    return {
        "sent_today": today,
        "sent_this_week": this_week,
        "daily_limit": account.daily_limit,
        "weekly_limit": account.weekly_limit,
        "daily_remaining": max(account.daily_limit - today, 0),
        "weekly_remaining": max(account.weekly_limit - this_week, 0),
    }


def next_day_start(account: LinkedInAccount, moment: datetime) -> datetime:
    zone = account_zone(account)
    local = to_local(account, moment)
    tomorrow = datetime.combine(local.date() + timedelta(days=1), time(0), tzinfo=zone)
    return next_window_start(account, tomorrow.astimezone(timezone.utc))


def next_week_start(account: LinkedInAccount, moment: datetime) -> datetime:
    zone = account_zone(account)
    local = to_local(account, moment)
    next_monday = local.date() + timedelta(days=7 - local.weekday())
    start = datetime.combine(next_monday, time(0), tzinfo=zone)
    return next_window_start(account, start.astimezone(timezone.utc))


def send_decision(db: Session, account: LinkedInAccount, moment: datetime) -> dict:
    """Whether this account may send right now, and when to look again."""
    if account.status == "needs_reauth":
        return {"send": False, "reason": "needs_reauth", "retry_at": None}
    if account.status == "paused":
        return {"send": False, "reason": "paused", "retry_at": None}

    if not within_window(account, moment):
        return {
            "send": False,
            "reason": "outside_window",
            "retry_at": next_window_start(account, moment),
        }

    quota = quota_state(db, account, moment)
    if quota["weekly_remaining"] <= 0:
        return {
            "send": False,
            "reason": "weekly_limit",
            "retry_at": next_week_start(account, moment),
            "quota": quota,
        }
    if quota["daily_remaining"] <= 0:
        return {
            "send": False,
            "reason": "daily_limit",
            "retry_at": next_day_start(account, moment),
            "quota": quota,
        }

    scheduled = as_utc(account.next_send_at)
    if scheduled and scheduled > as_utc(moment):
        return {"send": False, "reason": "waiting", "retry_at": scheduled, "quota": quota}

    return {"send": True, "reason": "ok", "retry_at": None, "quota": quota}
