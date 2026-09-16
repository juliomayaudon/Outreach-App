"""Google sign-in, authorization code flow.

Anyone with a verified address in the allowed Workspace domain gets an
account on first sign-in. The domain is enforced here, against the claims of
a signature-verified id_token, and never against anything the browser sent:
the `hd` parameter on the way out is only a hint for Google's account
chooser, and a determined person can edit it.
"""
from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx

from .config import get_settings

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
SCOPES = "openid email profile"
CALLBACK_PATH = "/api/auth/google/callback"


class OAuthError(Exception):
    """A reason worth showing the person on the login screen."""


def enabled() -> bool:
    return get_settings().google_enabled


def new_state() -> str:
    return secrets.token_urlsafe(24)


def redirect_uri(fallback_base_url: str = "") -> str:
    base = get_settings().base_url or fallback_base_url.rstrip("/")
    return f"{base}{CALLBACK_PATH}"


def authorize_url(state: str, uri: str) -> str:
    settings = get_settings()
    query = {
        "client_id": settings.google_client_id,
        "redirect_uri": uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    if settings.google_allowed_domain:
        query["hd"] = settings.google_allowed_domain
    return f"{AUTH_ENDPOINT}?{urlencode(query)}"


def exchange_code(code: str, uri: str) -> str:
    """Trades the one-time code for an id_token, still unverified here."""
    settings = get_settings()
    try:
        response = httpx.post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": uri,
                "grant_type": "authorization_code",
            },
            timeout=15,
        )
    except httpx.HTTPError as error:
        raise OAuthError("Could not reach Google. Try again.") from error
    if response.status_code != 200:
        # The body carries the client secret's fate; keep it out of the UI.
        raise OAuthError("Google rejected the sign-in. Try again.")
    token = response.json().get("id_token")
    if not token:
        raise OAuthError("Google did not return an identity token.")
    return token


def verified_identity(raw_id_token: str) -> dict:
    """Verifies signature, audience and domain. Returns the email and name."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    settings = get_settings()
    try:
        claims = google_id_token.verify_oauth2_token(
            raw_id_token, google_requests.Request(), settings.google_client_id
        )
    except ValueError as error:
        raise OAuthError("That sign-in could not be verified.") from error
    return identity_from_claims(claims)


def identity_from_claims(claims: dict) -> dict:
    """The domain rules, split out so they can be tested without a network."""
    settings = get_settings()
    email = str(claims.get("email") or "").strip().lower()
    if not email:
        raise OAuthError("That Google account has no address.")
    if not claims.get("email_verified"):
        raise OAuthError("That Google address is not verified.")

    domain = (settings.google_allowed_domain or "").strip().lower()
    if domain:
        hosted = str(claims.get("hd") or "").strip().lower()
        # Both checks: hd is absent on personal gmail accounts, and the
        # address is what every other table in the app keys off.
        if hosted != domain or not email.endswith(f"@{domain}"):
            raise OAuthError(f"Only {domain} accounts can sign in here.")
    return {"email": email, "name": str(claims.get("name") or "").strip()}
