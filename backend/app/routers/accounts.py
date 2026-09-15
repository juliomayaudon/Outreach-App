from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import current_user
from ..linkedin import LinkedInClient, parse_token_blob
from ..models import Campaign, Invitation, LinkedInAccount, User, utcnow
from ..schemas import AccountCreate, AccountOut, AccountUpdate
from ..scheduling import quota_state, within_window
from ..security import decrypt_json, encrypt_json

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def visible_accounts(db: Session, user: User):
    statement = select(LinkedInAccount).order_by(LinkedInAccount.id)
    if not user.is_admin:
        statement = statement.where(LinkedInAccount.owner_id == user.id)
    return list(db.scalars(statement))


def get_account_or_404(db: Session, user: User, account_id: int) -> LinkedInAccount:
    account = db.get(LinkedInAccount, account_id)
    if account is None or (not user.is_admin and account.owner_id != user.id):
        raise HTTPException(status_code=404, detail="Account not found")
    return account


def serialize(db: Session, account: LinkedInAccount) -> AccountOut:
    now = utcnow()
    quota = quota_state(db, account, now)
    pending = int(
        db.scalar(
            select(func.count(Invitation.id))
            .join(Campaign, Campaign.id == Invitation.campaign_id)
            .where(
                Invitation.account_id == account.id,
                Invitation.status == "pending",
                Campaign.status == "running",
            )
        )
        or 0
    )
    owner = db.get(User, account.owner_id)
    return AccountOut(
        id=account.id,
        label=account.label,
        linkedin_name=account.linkedin_name,
        owner_id=account.owner_id,
        owner_name=(owner.name or owner.email) if owner else "",
        status=account.status,
        status_detail=account.status_detail,
        timezone=account.timezone,
        daily_limit=account.daily_limit,
        weekly_limit=account.weekly_limit,
        window_start_hour=account.window_start_hour,
        window_end_hour=account.window_end_hour,
        skip_weekends=account.skip_weekends,
        min_delay_seconds=account.min_delay_seconds,
        max_delay_seconds=account.max_delay_seconds,
        next_send_at=account.next_send_at,
        last_checked_at=account.last_checked_at,
        pending=pending,
        in_window=within_window(account, now),
        **{k: quota[k] for k in ("sent_today", "sent_this_week", "daily_remaining", "weekly_remaining")},
    )


def _clamp_limits(daily: int, weekly: int) -> tuple[int, int]:
    settings = get_settings()
    return min(daily, settings.max_daily_limit), min(weekly, settings.max_weekly_limit)


@router.get("", response_model=list[AccountOut])
def list_accounts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [serialize(db, account) for account in visible_accounts(db, user)]


@router.post("", response_model=AccountOut, status_code=201)
def create_account(
    payload: AccountCreate, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    try:
        tokens = parse_token_blob(payload.tokens)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    client = LinkedInClient(tokens=tokens, user_agent=str(tokens.get("user-agent", "")))
    if client.missing_cookies:
        raise HTTPException(
            status_code=400,
            detail="The tokens are missing: " + ", ".join(client.missing_cookies),
        )
    check = client.check_session()

    daily, weekly = _clamp_limits(payload.daily_limit, payload.weekly_limit)
    account = LinkedInAccount(
        owner_id=user.id,
        label=payload.label.strip(),
        linkedin_name=check.name,
        cookies_encrypted=encrypt_json(tokens),
        user_agent=str(tokens.get("user-agent", "")),
        timezone=payload.timezone,
        daily_limit=daily,
        weekly_limit=weekly,
        window_start_hour=payload.window_start_hour,
        window_end_hour=payload.window_end_hour,
        skip_weekends=payload.skip_weekends,
        min_delay_seconds=min(payload.min_delay_seconds, payload.max_delay_seconds),
        max_delay_seconds=max(payload.min_delay_seconds, payload.max_delay_seconds),
        status="active" if check.ok else "needs_reauth",
        status_detail="" if check.ok else check.detail,
        last_checked_at=utcnow(),
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return serialize(db, account)


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(
    account_id: int,
    payload: AccountUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    account = get_account_or_404(db, user, account_id)

    if payload.tokens:
        try:
            tokens = parse_token_blob(payload.tokens)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        client = LinkedInClient(tokens=tokens, user_agent=str(tokens.get("user-agent", "")))
        if client.missing_cookies:
            raise HTTPException(
                status_code=400,
                detail="The tokens are missing: " + ", ".join(client.missing_cookies),
            )
        check = client.check_session()
        account.cookies_encrypted = encrypt_json(tokens)
        account.user_agent = str(tokens.get("user-agent", ""))
        account.last_checked_at = utcnow()
        account.status = "active" if check.ok else "needs_reauth"
        account.status_detail = "" if check.ok else check.detail
        if check.name:
            account.linkedin_name = check.name

    simple_fields = (
        "label",
        "window_start_hour",
        "window_end_hour",
        "skip_weekends",
        "timezone",
    )
    for field in simple_fields:
        value = getattr(payload, field)
        if value is not None:
            setattr(account, field, value)

    if payload.daily_limit is not None or payload.weekly_limit is not None:
        daily, weekly = _clamp_limits(
            payload.daily_limit or account.daily_limit,
            payload.weekly_limit or account.weekly_limit,
        )
        account.daily_limit, account.weekly_limit = daily, weekly

    if payload.min_delay_seconds is not None or payload.max_delay_seconds is not None:
        minimum = payload.min_delay_seconds or account.min_delay_seconds
        maximum = payload.max_delay_seconds or account.max_delay_seconds
        account.min_delay_seconds, account.max_delay_seconds = min(minimum, maximum), max(
            minimum, maximum
        )

    if payload.status in ("active", "paused"):
        if payload.status == "active" and account.status == "needs_reauth":
            raise HTTPException(
                status_code=400,
                detail="Paste fresh tokens before reactivating this account.",
            )
        account.status = payload.status
        if payload.status == "active":
            account.status_detail = ""

    db.commit()
    db.refresh(account)
    return serialize(db, account)


@router.post("/{account_id}/test", response_model=AccountOut)
def test_account(
    account_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    account = get_account_or_404(db, user, account_id)
    tokens = decrypt_json(account.cookies_encrypted)
    if not tokens:
        raise HTTPException(
            status_code=400,
            detail="The stored tokens cannot be read (APP_SECRET changed?). Paste them again.",
        )
    check = LinkedInClient(tokens=tokens, user_agent=account.user_agent).check_session()
    account.last_checked_at = utcnow()
    if check.ok:
        account.linkedin_name = check.name or account.linkedin_name
        if account.status == "needs_reauth":
            account.status = "active"
        account.status_detail = ""
    else:
        account.status = "needs_reauth"
        account.status_detail = check.detail
    db.commit()
    db.refresh(account)
    return serialize(db, account)


@router.delete("/{account_id}", status_code=204)
def delete_account(
    account_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    account = get_account_or_404(db, user, account_id)
    campaigns = int(
        db.scalar(select(func.count(Campaign.id)).where(Campaign.account_id == account.id)) or 0
    )
    if campaigns:
        raise HTTPException(
            status_code=400,
            detail=f"This account has {campaigns} campaign(s). Delete them first or pause the account.",
        )
    db.delete(account)
    db.commit()
