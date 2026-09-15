from datetime import datetime, timedelta, timezone

from app.linkedin import SendResult
from app.models import Campaign, Invitation, LinkedInAccount
from app.worker import DripWorker, result_text

NOW = datetime(2026, 9, 15, 14, 0, tzinfo=timezone.utc)  # Tuesday


class FakeClient:
    """Stands in for LinkedInClient; returns a scripted result per profile."""

    def __init__(self, results=None, default=None):
        self.results = results or {}
        self.default = default or SendResult(status="sent", code="OK", http_status=200)
        self.calls = []

    def send_invitation(self, profile_id, message=""):
        self.calls.append((profile_id, message))
        return self.results.get(profile_id, self.default)


def worker_with(client):
    return DripWorker(poll_seconds=1, client_factory=lambda account: client)


def test_one_invitation_per_tick_and_pacing(db, campaign_factory, account):
    campaign_factory(["ACoAAA0001", "ACoAAA0002", "ACoAAA0003"])
    client = FakeClient()
    worker = worker_with(client)

    worker.tick(NOW)
    assert len(client.calls) == 1

    # Too soon: the account is paced by next_send_at.
    worker.tick(NOW + timedelta(seconds=2))
    assert len(client.calls) == 1

    worker.tick(NOW + timedelta(seconds=30))
    worker.tick(NOW + timedelta(seconds=60))
    assert len(client.calls) == 3

    db.expire_all()
    statuses = [i.status for i in db.query(Invitation).order_by(Invitation.id)]
    assert statuses == ["sent", "sent", "sent"]
    assert db.query(Campaign).first().status == "completed"


def test_daily_limit_stops_the_account(db, campaign_factory, account):
    account.daily_limit = 2
    db.commit()
    campaign_factory(["ACoAAA0001", "ACoAAA0002", "ACoAAA0003"])
    client = FakeClient()
    worker = worker_with(client)

    for minutes in range(6):
        worker.tick(NOW + timedelta(minutes=minutes))

    assert len(client.calls) == 2
    db.expire_all()
    assert db.query(Invitation).filter(Invitation.status == "sent").count() == 2
    assert db.query(Invitation).filter(Invitation.status == "pending").count() == 1

    # Next day the quota resets.
    for minutes in range(3):
        worker.tick(NOW + timedelta(days=1, minutes=minutes))
    assert len(client.calls) == 3


def test_weekly_limit_stops_the_account(db, campaign_factory, account):
    account.daily_limit = 10
    account.weekly_limit = 1
    db.commit()
    campaign_factory(["ACoAAA0001", "ACoAAA0002"])
    client = FakeClient()
    worker = worker_with(client)

    for minutes in range(4):
        worker.tick(NOW + timedelta(minutes=minutes))
    assert len(client.calls) == 1

    # Still blocked tomorrow, unblocked next week.
    worker.tick(NOW + timedelta(days=1))
    assert len(client.calls) == 1
    worker.tick(NOW + timedelta(days=7))
    assert len(client.calls) == 2


def test_expired_session_pauses_the_account_and_keeps_the_row(db, campaign_factory, account):
    campaign_factory(["ACoAAA0001", "ACoAAA0002"])
    client = FakeClient(
        default=SendResult(
            status="failed", code="AUTH", message="expired", http_status=999,
            retry=True, account_action="needs_reauth",
        )
    )
    worker = worker_with(client)

    worker.tick(NOW)
    db.expire_all()
    refreshed = db.get(LinkedInAccount, account.id)
    assert refreshed.status == "needs_reauth"
    assert db.query(Invitation).filter(Invitation.status == "pending").count() == 2

    # A paused account is not picked up again.
    worker.tick(NOW + timedelta(minutes=5))
    assert len(client.calls) == 1


def test_rate_limit_backs_off_then_resumes(db, campaign_factory, account):
    campaign_factory(["ACoAAA0001"])
    client = FakeClient(
        results={
            "ACoAAA0001": SendResult(
                status="failed", code="RATE_LIMIT", http_status=429,
                retry=True, account_action="cooldown",
            )
        }
    )
    worker = worker_with(client)
    worker.tick(NOW)

    db.expire_all()
    assert db.get(LinkedInAccount, account.id).status == "cooldown"
    assert db.query(Invitation).first().status == "pending"
    assert db.query(Invitation).first().attempts == 1

    worker.tick(NOW + timedelta(minutes=5))
    assert len(client.calls) == 1  # still cooling down

    client.results = {}
    worker.tick(NOW + timedelta(minutes=25))
    db.expire_all()
    assert db.query(Invitation).first().status == "sent"
    assert db.get(LinkedInAccount, account.id).status == "active"


def test_row_fails_for_good_after_max_attempts(db, campaign_factory, account):
    campaign_factory(["ACoAAA0001"])
    client = FakeClient(
        default=SendResult(status="failed", code="SERVER_ERROR", http_status=500, retry=True)
    )
    worker = worker_with(client)
    for minutes in range(12):
        worker.tick(NOW + timedelta(minutes=minutes))

    db.expire_all()
    invitation = db.query(Invitation).first()
    assert invitation.status == "failed"
    assert invitation.attempts == 5


def test_skipped_rows_are_terminal(db, campaign_factory, account):
    campaign_factory(["ACoAAA0001"])
    client = FakeClient(
        default=SendResult(status="skipped", code="ALREADY_INVITED", http_status=400)
    )
    worker = worker_with(client)
    worker.tick(NOW)
    worker.tick(NOW + timedelta(minutes=5))

    assert len(client.calls) == 1
    db.expire_all()
    assert db.query(Invitation).first().status == "skipped"


def test_paused_campaign_is_not_processed(db, campaign_factory, account):
    campaign_factory(["ACoAAA0001"], status="paused")
    client = FakeClient()
    worker_with(client).tick(NOW)
    assert client.calls == []


def test_outside_the_window_nothing_is_sent(db, campaign_factory, account):
    account.window_start_hour = 9
    account.window_end_hour = 18
    account.timezone = "America/Guayaquil"
    db.commit()
    campaign_factory(["ACoAAA0001"])
    client = FakeClient()
    worker = worker_with(client)

    worker.tick(datetime(2026, 9, 15, 5, 0, tzinfo=timezone.utc))  # 00:00 local
    assert client.calls == []
    worker.tick(datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc))  # 10:00 local
    assert len(client.calls) == 1


def test_sheet_writeback_is_queued_and_flushed(db, campaign_factory, account, monkeypatch):
    campaign_factory(["ACoAAA0001"], source_type="sheet", write_back=True,
                     sheet_url="https://docs.google.com/spreadsheets/d/X/edit",
                     sheet_tab="CR", result_column="Result")
    written = []
    monkeypatch.setattr("app.sheets.sheets_enabled", lambda: True)
    monkeypatch.setattr(
        "app.sheets.write_results",
        lambda url, tab, column, updates: written.append((url, tab, column, updates)) or len(updates),
    )

    worker = worker_with(FakeClient())
    worker.tick(NOW)

    assert written and written[0][3][0][0] == 2  # sheet row number
    assert "Connection request sent!" in written[0][3][0][1]
    db.expire_all()
    assert db.query(Invitation).first().sheet_synced is True


def test_result_text_for_failures(db, campaign_factory, account):
    campaign_factory(["ACoAAA0001"])
    invitation = db.query(Invitation).first()
    invitation.status = "failed"
    invitation.http_status = 429
    invitation.error_code = "RATE_LIMIT"
    invitation.error_message = "slow down"
    assert result_text(invitation).startswith("Not sent (429) - RATE_LIMIT - slow down")
