from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import Campaign, Invitation, LinkedInAccount, User, as_utc, utcnow

router = APIRouter(prefix="/api/stats", tags=["stats"])

MONTH_LABELS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def user_zone(user: User) -> ZoneInfo:
    try:
        return ZoneInfo(user.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def start_of_local_day(zone: ZoneInfo, day: date) -> datetime:
    return datetime.combine(day, time(0), tzinfo=zone).astimezone(timezone.utc)


@router.get("/overview")
def overview(
    scope: str = Query("me", pattern="^(me|team)$"),
    weeks: int = Query(12, ge=4, le=52),
    months: int = Query(12, ge=3, le=24),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    team = scope == "team" and user.is_admin
    zone = user_zone(user)
    now = utcnow()
    today_local = now.astimezone(zone).date()

    def scoped(statement):
        return statement if team else statement.where(Invitation.owner_id == user.id)

    # -- totals by status ---------------------------------------------------
    status_rows = db.execute(
        scoped(select(Invitation.status, func.count(Invitation.id)).group_by(Invitation.status))
    ).all()
    by_status = {"sent": 0, "pending": 0, "failed": 0, "skipped": 0}
    for status, count in status_rows:
        by_status[status] = count

    def sent_since(moment: datetime) -> int:
        return int(
            db.scalar(
                scoped(
                    select(func.count(Invitation.id)).where(
                        Invitation.status == "sent", Invitation.sent_at >= moment
                    )
                )
            )
            or 0
        )

    monday = today_local - timedelta(days=today_local.weekday())
    first_of_month = today_local.replace(day=1)
    totals = {
        "today": sent_since(start_of_local_day(zone, today_local)),
        "this_week": sent_since(start_of_local_day(zone, monday)),
        "this_month": sent_since(start_of_local_day(zone, first_of_month)),
        "last_7_days": sent_since(start_of_local_day(zone, today_local - timedelta(days=6))),
        "last_30_days": sent_since(start_of_local_day(zone, today_local - timedelta(days=29))),
        "all_time": by_status["sent"],
        "pending": by_status["pending"],
    }

    # -- time series --------------------------------------------------------
    cutoff_day = (first_of_month - timedelta(days=31 * (months - 1))).replace(day=1)
    cutoff = start_of_local_day(zone, min(cutoff_day, today_local - timedelta(weeks=weeks)))
    series_rows = db.execute(
        scoped(
            select(Invitation.status, Invitation.sent_at, Invitation.updated_at).where(
                (Invitation.sent_at >= cutoff) | (Invitation.updated_at >= cutoff)
            )
        )
    ).all()

    daily_sent: dict[date, int] = defaultdict(int)
    weekly: dict[tuple[int, int], dict] = defaultdict(lambda: {"sent": 0, "failed": 0, "skipped": 0})
    monthly: dict[tuple[int, int], dict] = defaultdict(lambda: {"sent": 0, "failed": 0, "skipped": 0})

    for status, sent_at, updated_at in series_rows:
        moment = as_utc(sent_at) if status == "sent" else as_utc(updated_at)
        if moment is None or status not in ("sent", "failed", "skipped"):
            continue
        local_day = moment.astimezone(zone).date()
        iso_year, iso_week, _ = local_day.isocalendar()
        weekly[(iso_year, iso_week)][status] += 1
        monthly[(local_day.year, local_day.month)][status] += 1
        if status == "sent":
            daily_sent[local_day] += 1

    weekly_series = []
    for offset in range(weeks - 1, -1, -1):
        day = monday - timedelta(weeks=offset)
        iso_year, iso_week, _ = day.isocalendar()
        bucket = weekly.get((iso_year, iso_week), {"sent": 0, "failed": 0, "skipped": 0})
        weekly_series.append(
            {
                "period": f"{iso_year}-W{iso_week:02d}",
                "label": day.strftime("%d %b"),
                "start": day.isoformat(),
                **bucket,
            }
        )

    monthly_series = []
    year, month = first_of_month.year, first_of_month.month
    cursor = []
    for _ in range(months):
        cursor.append((year, month))
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    for year, month in reversed(cursor):
        bucket = monthly.get((year, month), {"sent": 0, "failed": 0, "skipped": 0})
        monthly_series.append(
            {
                "period": f"{year}-{month:02d}",
                "label": f"{MONTH_LABELS[month - 1]} {str(year)[2:]}",
                **bucket,
            }
        )

    daily_series = []
    for offset in range(29, -1, -1):
        day = today_local - timedelta(days=offset)
        daily_series.append(
            {"date": day.isoformat(), "label": day.strftime("%d %b"), "sent": daily_sent.get(day, 0)}
        )

    # -- per account --------------------------------------------------------
    account_statement = select(LinkedInAccount).order_by(LinkedInAccount.id)
    if not team:
        account_statement = account_statement.where(LinkedInAccount.owner_id == user.id)
    accounts = list(db.scalars(account_statement))

    account_rows = db.execute(
        scoped(
            select(Invitation.account_id, Invitation.status, func.count(Invitation.id)).group_by(
                Invitation.account_id, Invitation.status
            )
        )
    ).all()
    per_account: dict[int, dict] = defaultdict(lambda: {"sent": 0, "pending": 0, "failed": 0, "skipped": 0})
    for account_id, status, count in account_rows:
        per_account[account_id][status] = count

    week_start = start_of_local_day(zone, today_local - timedelta(days=6))
    recent_rows = db.execute(
        scoped(
            select(Invitation.account_id, func.count(Invitation.id))
            .where(Invitation.status == "sent", Invitation.sent_at >= week_start)
            .group_by(Invitation.account_id)
        )
    ).all()
    sent_7d = {account_id: count for account_id, count in recent_rows}

    by_account = [
        {
            "account_id": account.id,
            "label": account.label,
            "owner_id": account.owner_id,
            "status": account.status,
            "status_detail": account.status_detail,
            "daily_limit": account.daily_limit,
            "weekly_limit": account.weekly_limit,
            "sent_7d": sent_7d.get(account.id, 0),
            **per_account.get(account.id, {"sent": 0, "pending": 0, "failed": 0, "skipped": 0}),
        }
        for account in accounts
    ]

    # -- recent activity ----------------------------------------------------
    recent_statement = (
        scoped(select(Invitation).where(Invitation.status == "sent"))
        .order_by(Invitation.sent_at.desc())
        .limit(12)
    )
    account_labels = {account.id: account.label for account in accounts}
    recent_invitations = list(db.scalars(recent_statement))
    campaign_names = dict(
        db.execute(
            select(Campaign.id, Campaign.name).where(
                Campaign.id.in_({invitation.campaign_id for invitation in recent_invitations} or {0})
            )
        ).all()
    )
    recent = [
        {
            "id": invitation.id,
            "full_name": invitation.full_name or invitation.profile_id,
            "company": invitation.company,
            "title": invitation.title,
            "account": account_labels.get(invitation.account_id, ""),
            "campaign": campaign_names.get(invitation.campaign_id, ""),
            "sent_at": as_utc(invitation.sent_at).isoformat() if invitation.sent_at else None,
        }
        for invitation in recent_invitations
    ]

    success_base = by_status["sent"] + by_status["failed"]
    return {
        "scope": "team" if team else "me",
        "timezone": str(zone),
        "totals": totals,
        "by_status": by_status,
        "success_rate": round(by_status["sent"] / success_base * 100, 1) if success_base else None,
        "daily": daily_series,
        "weekly": weekly_series,
        "monthly": monthly_series,
        "by_account": by_account,
        "recent": recent,
    }
