from datetime import datetime, timezone

from app.models import LinkedInAccount
from app.scheduling import (
    next_day_start,
    next_week_start,
    next_window_start,
    quota_state,
    send_decision,
    to_local,
    within_window,
)

TUESDAY_09 = datetime(2026, 9, 15, 14, 0, tzinfo=timezone.utc)  # 09:00 in Guayaquil


def guayaquil(**overrides):
    defaults = dict(
        id=1, timezone="America/Guayaquil", window_start_hour=9, window_end_hour=18,
        skip_weekends=True, daily_limit=20, weekly_limit=100, status="active",
        min_delay_seconds=60, max_delay_seconds=120,
    )
    defaults.update(overrides)
    return LinkedInAccount(**defaults)


def test_window_respects_local_hours():
    account = guayaquil()
    assert within_window(account, TUESDAY_09)
    assert not within_window(account, datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc))
    assert not within_window(account, datetime(2026, 9, 15, 23, 0, tzinfo=timezone.utc))


def test_window_skips_weekends():
    account = guayaquil()
    saturday = datetime(2026, 9, 19, 15, 0, tzinfo=timezone.utc)
    assert not within_window(account, saturday)
    resume = next_window_start(account, saturday)
    assert to_local(account, resume).weekday() == 0 and to_local(account, resume).hour == 9


def test_window_can_be_always_open():
    account = guayaquil(window_start_hour=0, window_end_hour=0, skip_weekends=False)
    assert within_window(account, datetime(2026, 9, 19, 3, 0, tzinfo=timezone.utc))


def test_next_day_and_week_start():
    account = guayaquil()
    assert to_local(account, next_day_start(account, TUESDAY_09)).day == 16
    next_monday = to_local(account, next_week_start(account, TUESDAY_09))
    assert next_monday.weekday() == 0 and next_monday.day == 21


def test_send_decision_blocks_on_quota(db, account, campaign_factory):
    from app.models import Invitation

    account.daily_limit = 1
    account.weekly_limit = 5
    db.commit()
    campaign_factory(["ACoAAA0001", "ACoAAA0002"])

    assert send_decision(db, account, TUESDAY_09)["send"] is True

    invitation = db.query(Invitation).first()
    invitation.status = "sent"
    invitation.sent_at = TUESDAY_09
    db.commit()

    decision = send_decision(db, account, TUESDAY_09)
    assert decision["send"] is False and decision["reason"] == "daily_limit"
    assert quota_state(db, account, TUESDAY_09)["sent_today"] == 1


def test_send_decision_honours_account_status(db, account):
    account.status = "paused"
    db.commit()
    assert send_decision(db, account, TUESDAY_09)["reason"] == "paused"
    account.status = "needs_reauth"
    db.commit()
    assert send_decision(db, account, TUESDAY_09)["reason"] == "needs_reauth"
