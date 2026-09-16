import json
from datetime import datetime, timedelta, timezone

import pytest

from app.linkedin import SessionCheck
from app.models import Invitation, User
from app.security import hash_password

CSV = (
    b"Full Name,vmid,Company,Job Title\n"
    b"Julio Perez,ACoAAA0001,Kalungi,CTO\n"
    b"Ana Diaz,ACoAAA0002,Acme,CEO\n"
    b"Bad Row,julio-perez,X,Y\n"
)


class FakeLinkedInClient:
    ok = True

    def __init__(self, tokens=None, user_agent="", **kwargs):
        self.tokens = tokens or {}

    @property
    def missing_cookies(self):
        return [k for k in ("li_at", "JSESSIONID") if not self.tokens.get(k)]

    def check_session(self):
        if FakeLinkedInClient.ok:
            return SessionCheck(True, name="Julio Perez", http_status=200)
        return SessionCheck(False, detail="Session rejected", http_status=999)


@pytest.fixture
def fake_linkedin(monkeypatch):
    FakeLinkedInClient.ok = True
    monkeypatch.setattr("app.routers.accounts.LinkedInClient", FakeLinkedInClient)
    return FakeLinkedInClient


TOKENS = "{'li_at': 'AQED', 'JSESSIONID': 'ajax:1', 'csrf-token': 'ajax:1'}"


def create_account(client, label="Julio - Kalungi", **overrides):
    payload = {"label": label, "tokens": TOKENS, "timezone": "America/Guayaquil"}
    payload.update(overrides)
    response = client.post("/api/accounts", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def create_csv_campaign(client, account_id, name="Sept ABM"):
    mapping = {"vmid": "vmid", "full_name": "Full Name", "company": "Company", "title": "Job Title"}
    return client.post(
        "/api/campaigns/csv",
        files={"file": ("lista.csv", CSV, "text/csv")},
        data={
            "name": name,
            "account_id": str(account_id),
            "mapping": json.dumps(mapping),
            "note_template": "Hola {first_name}, vi que sos {title} en {company}.",
            "start_now": "true",
        },
    )


# --------------------------------------------------------------------------
def test_everything_needs_a_session():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as anonymous:
        for path in ("/api/accounts", "/api/campaigns", "/api/stats/overview", "/api/users"):
            assert anonymous.get(path).status_code == 401


def test_health_is_public():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as anonymous:
        assert anonymous.get("/api/health").json()["status"] == "ok"


def test_login_rejects_bad_credentials(client, user):
    assert client.post(
        "/api/auth/login", json={"email": user.email, "password": "wrong"}
    ).status_code == 401


def test_create_account_checks_the_session(client, fake_linkedin):
    account = create_account(client)
    assert account["status"] == "active"
    assert account["linkedin_name"] == "Julio Perez"
    assert account["daily_limit"] == 20 and account["weekly_limit"] == 100

    FakeLinkedInClient.ok = False
    broken = create_account(client, label="Expired one")
    assert broken["status"] == "needs_reauth"
    assert "rejected" in broken["status_detail"]


def test_account_limits_are_capped(client, fake_linkedin):
    account = create_account(client, daily_limit=500, weekly_limit=1000)
    assert account["daily_limit"] == 80  # MAX_DAILY_LIMIT
    assert account["weekly_limit"] == 200


def test_reactivating_a_broken_account_requires_new_tokens(client, fake_linkedin):
    FakeLinkedInClient.ok = False
    account = create_account(client)
    response = client.patch(f"/api/accounts/{account['id']}", json={"status": "active"})
    assert response.status_code == 400

    FakeLinkedInClient.ok = True
    fixed = client.patch(f"/api/accounts/{account['id']}", json={"tokens": TOKENS})
    assert fixed.status_code == 200 and fixed.json()["status"] == "active"


def test_csv_campaign_end_to_end(client, fake_linkedin, db):
    account = create_account(client)
    response = create_csv_campaign(client, account["id"])
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["queued"] == 2
    assert body["skipped"] == 1
    assert body["skipped_examples"][0]["value"] == "julio-perez"
    assert body["campaign"]["status"] == "running"
    assert body["campaign"]["total"] == 3

    rows = client.get(f"/api/campaigns/{body['campaign']['id']}/rows").json()
    queued = [r for r in rows if r["status"] == "pending"]
    assert queued[0]["message"] == "Hola Julio, vi que sos CTO en Kalungi."
    assert queued[0]["full_name"] == "Julio Perez"

    # The same list a second time does not queue anybody twice.
    again = create_csv_campaign(client, account["id"], name="Duplicate run").json()
    assert again["queued"] == 0 and again["skipped"] == 3


def test_campaign_pause_resume_and_retry(client, fake_linkedin, db):
    account = create_account(client)
    campaign_id = create_csv_campaign(client, account["id"]).json()["campaign"]["id"]

    assert client.post(f"/api/campaigns/{campaign_id}/status?action=pause").json()["status"] == "paused"
    assert client.post(f"/api/campaigns/{campaign_id}/status?action=resume").json()["status"] == "running"

    invitation = db.query(Invitation).filter(Invitation.status == "pending").first()
    invitation.status = "failed"
    invitation.error_code = "SERVER_ERROR"
    invitation.attempts = 5
    db.commit()

    retried = client.post(f"/api/campaigns/{campaign_id}/retry-failed").json()
    assert retried["failed"] == 0 and retried["pending"] == 2
    db.expire_all()
    assert db.get(Invitation, invitation.id).attempts == 0


def test_campaign_export_is_a_csv(client, fake_linkedin):
    account = create_account(client)
    campaign_id = create_csv_campaign(client, account["id"]).json()["campaign"]["id"]
    response = client.get(f"/api/campaigns/{campaign_id}/export")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert response.text.splitlines()[0].startswith("vmid,full_name")
    assert "ACoAAA0001" in response.text


def test_stats_overview(client, fake_linkedin, db):
    account = create_account(client)
    create_csv_campaign(client, account["id"])

    now = datetime.now(timezone.utc)
    for offset, invitation in enumerate(db.query(Invitation).filter(Invitation.status == "pending")):
        invitation.status = "sent"
        invitation.sent_at = now - timedelta(days=offset)
    db.commit()

    stats = client.get("/api/stats/overview").json()
    assert stats["totals"]["all_time"] == 2
    assert stats["totals"]["last_7_days"] == 2
    assert stats["by_status"]["sent"] == 2
    assert stats["by_status"]["skipped"] == 1
    assert len(stats["weekly"]) == 12 and len(stats["monthly"]) == 12
    assert len(stats["daily"]) == 30
    assert sum(week["sent"] for week in stats["weekly"]) == 2
    assert stats["by_account"][0]["label"] == "Julio - Kalungi"
    assert stats["by_account"][0]["sent_7d"] == 2
    assert stats["success_rate"] == 100.0
    assert len(stats["recent"]) == 2


def test_members_only_see_their_own_work(client, fake_linkedin, db):
    account = create_account(client)
    create_csv_campaign(client, account["id"])

    db.add(
        User(
            email="thais@kalungi.com",
            name="Thais",
            password_hash=hash_password("anotherpass1"),
            role="member",
        )
    )
    db.commit()

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as other:
        other.post(
            "/api/auth/login", json={"email": "thais@kalungi.com", "password": "anotherpass1"}
        )
        assert other.get("/api/campaigns").json() == []
        assert other.get("/api/accounts").json() == []
        assert other.get(f"/api/accounts/{account['id']}/test").status_code in (404, 405)
        assert other.get("/api/users").status_code == 403
        assert other.get("/api/stats/overview").json()["totals"]["all_time"] == 0


def test_sheet_campaign_requires_configuration(client, fake_linkedin):
    account = create_account(client)
    response = client.post(
        "/api/campaigns/sheet",
        json={
            "name": "From sheet",
            "account_id": account["id"],
            "url": "https://docs.google.com/spreadsheets/d/XYZ/edit",
            "tab": "CR",
            "mapping": {"vmid": "vmid"},
        },
    )
    assert response.status_code == 400
    assert "GOOGLE_SERVICE_ACCOUNT_JSON" in response.json()["detail"]


def test_health_reports_whether_the_worker_thread_exists(client):
    """RUN_WORKER is off in the tests, so this must not claim otherwise."""
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["worker"] is False
