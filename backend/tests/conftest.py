import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# Must be set before the app modules read the settings.
os.environ.update(
    DATABASE_URL=f"sqlite:///{BACKEND / 'test.db'}",
    APP_SECRET="test-secret",
    ADMIN_EMAIL="admin@test.com",
    ADMIN_PASSWORD="adminpass123",
    RUN_WORKER="false",
    COOKIE_SECURE="false",
    GOOGLE_SERVICE_ACCOUNT_JSON="",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Campaign, Invitation, LinkedInAccount, User  # noqa: E402
from app.security import encrypt_json, hash_password  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def user(db):
    account = User(
        email="julio@kalungi.com",
        name="Julio",
        password_hash=hash_password("testpass123"),
        role="admin",
        timezone="America/Guayaquil",
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@pytest.fixture
def client(user):
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/auth/login", json={"email": user.email, "password": "testpass123"}
        )
        assert response.status_code == 200
        yield test_client


@pytest.fixture
def account(db, user):
    linkedin_account = LinkedInAccount(
        owner_id=user.id,
        label="Julio - Kalungi",
        cookies_encrypted=encrypt_json(
            {"li_at": "token", "JSESSIONID": "ajax:1", "csrf-token": "ajax:1"}
        ),
        user_agent="Mozilla/5.0",
        timezone="UTC",
        daily_limit=5,
        weekly_limit=20,
        window_start_hour=0,
        window_end_hour=0,  # always open
        skip_weekends=False,
        min_delay_seconds=10,
        max_delay_seconds=10,
        status="active",
    )
    db.add(linkedin_account)
    db.commit()
    db.refresh(linkedin_account)
    return linkedin_account


def make_campaign(db, user, account, profile_ids, **kwargs):
    campaign = Campaign(
        owner_id=user.id,
        account_id=account.id,
        name=kwargs.pop("name", "Test campaign"),
        status=kwargs.pop("status", "running"),
        source_type=kwargs.pop("source_type", "csv"),
        source_name="test.csv",
        **kwargs,
    )
    db.add(campaign)
    db.flush()
    for index, profile_id in enumerate(profile_ids):
        db.add(
            Invitation(
                campaign_id=campaign.id,
                account_id=account.id,
                owner_id=user.id,
                profile_id=profile_id,
                raw_value=profile_id,
                full_name=f"Person {index}",
                status="pending",
                sheet_row=index + 2,
            )
        )
    db.commit()
    db.refresh(campaign)
    return campaign


@pytest.fixture
def campaign_factory(db, user, account):
    def factory(profile_ids, **kwargs):
        return make_campaign(db, user, account, profile_ids, **kwargs)

    return factory
