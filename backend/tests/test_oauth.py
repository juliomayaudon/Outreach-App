"""Google sign-in.

The domain is the whole security boundary here: anyone who gets past it gets
an account without anybody approving it. So the rules are tested against the
claims directly, with no network in the way.
"""
import pytest
from sqlalchemy import select

from app import oauth
from app.config import get_settings
from app.models import User
from app.security import verify_password

DOMAIN = "kalungi.com"


def claims(**overrides) -> dict:
    base = {
        "email": f"someone@{DOMAIN}",
        "email_verified": True,
        "hd": DOMAIN,
        "name": "Someone",
    }
    base.update(overrides)
    return base


@pytest.fixture
def google_configured(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "a-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "a-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# -- the domain rule -------------------------------------------------------
def test_an_address_in_the_domain_is_accepted():
    identity = oauth.identity_from_claims(claims())
    assert identity == {"email": f"someone@{DOMAIN}", "name": "Someone"}


def test_a_personal_gmail_account_is_refused():
    # No hd claim at all is what a consumer account looks like.
    with pytest.raises(oauth.OAuthError):
        oauth.identity_from_claims(claims(email="someone@gmail.com", hd=None))


def test_another_workspace_domain_is_refused():
    with pytest.raises(oauth.OAuthError):
        oauth.identity_from_claims(claims(email="someone@example.com", hd="example.com"))


def test_an_address_that_only_looks_like_the_domain_is_refused():
    # hd says the right thing but the address does not belong to it.
    with pytest.raises(oauth.OAuthError):
        oauth.identity_from_claims(claims(email=f"someone@not-{DOMAIN}", hd=DOMAIN))


def test_an_unverified_address_is_refused():
    with pytest.raises(oauth.OAuthError):
        oauth.identity_from_claims(claims(email_verified=False))


def test_the_address_is_normalised():
    identity = oauth.identity_from_claims(claims(email=f"  Someone@{DOMAIN.upper()}  "))
    assert identity["email"] == f"someone@{DOMAIN}"


# -- the endpoints ---------------------------------------------------------
def test_sign_in_with_google_is_off_until_it_is_configured(client):
    body = client.get("/api/auth/config").json()
    assert body["google_enabled"] is False
    assert body["google_domain"] == DOMAIN


def test_the_routes_are_absent_while_it_is_unconfigured(client):
    assert client.get("/api/auth/google/start", follow_redirects=False).status_code == 404


def test_it_is_advertised_once_configured(client, google_configured):
    assert client.get("/api/auth/config").json()["google_enabled"] is True


def test_the_callback_refuses_a_state_it_did_not_issue(client, google_configured):
    response = client.get(
        "/api/auth/google/callback?code=abc&state=forged", follow_redirects=False
    )
    assert response.status_code == 303
    assert "auth_error" in response.headers["location"]


def test_a_first_sign_in_creates_a_member_who_has_no_password(
    client, db, google_configured, monkeypatch
):
    monkeypatch.setattr(oauth, "exchange_code", lambda code, uri: "an-id-token")
    monkeypatch.setattr(
        oauth,
        "verified_identity",
        lambda token: {"email": f"nuevo@{DOMAIN}", "name": "Nuevo"},
    )
    client.cookies.set("outreach_oauth_state", "the-state")

    response = client.get(
        "/api/auth/google/callback?code=abc&state=the-state", follow_redirects=False
    )

    assert response.status_code == 303
    created = db.scalar(select(User).where(User.email == f"nuevo@{DOMAIN}"))
    assert created is not None
    assert created.role == "member"
    assert created.is_active is True
    # Nothing must authenticate as this account through the password form.
    assert verify_password("", created.password_hash) is False
    assert verify_password("anything", created.password_hash) is False


def test_a_disabled_account_is_not_let_back_in_through_google(
    client, db, google_configured, monkeypatch
):
    db.add(
        User(email=f"fuera@{DOMAIN}", name="Fuera", password_hash="", role="member", is_active=False)
    )
    db.commit()
    monkeypatch.setattr(oauth, "exchange_code", lambda code, uri: "an-id-token")
    monkeypatch.setattr(
        oauth, "verified_identity", lambda token: {"email": f"fuera@{DOMAIN}", "name": "Fuera"}
    )
    client.cookies.set("outreach_oauth_state", "the-state")

    response = client.get(
        "/api/auth/google/callback?code=abc&state=the-state", follow_redirects=False
    )

    assert response.status_code == 303
    assert "auth_error" in response.headers["location"]
