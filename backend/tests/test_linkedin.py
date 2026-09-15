import json

import httpx
import pytest

from app.linkedin import (
    LinkedInClient,
    build_cookies,
    classify_error,
    normalize_profile_id,
    parse_token_blob,
)

TOKENS = {
    "li_at": "AQED-token",
    "JSESSIONID": "ajax:123",
    "csrf-token": "ajax:123",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/151",
}


def client_with(handler):
    return LinkedInClient(
        tokens=TOKENS,
        user_agent=TOKENS["user-agent"],
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ACoAAABBBCCC", "ACoAAABBBCCC"),
        ("  urn:li:fsd_profile:ACoAAABBBCCC ", "ACoAAABBBCCC"),
        ("https://www.linkedin.com/in/ACoAAABBBCCC/?original=X", "ACoAAABBBCCC"),
        (None, ""),
        ("", ""),
    ],
)
def test_normalize_profile_id(raw, expected):
    assert normalize_profile_id(raw) == expected


def test_cookies_never_include_the_user_agent():
    """A user-agent sent as a cookie corrupts the Cookie header (it has ';')."""
    cookies = build_cookies(TOKENS)
    assert set(cookies) == {"li_at", "JSESSIONID"}
    assert cookies["JSESSIONID"] == '"ajax:123"'
    assert ";" not in "".join(cookies.values())


def test_parse_token_blob_accepts_python_dict_and_json():
    assert parse_token_blob("{'li_at': 'a'}") == {"li_at": "a"}
    assert parse_token_blob('{"li_at": "a"}') == {"li_at": "a"}
    with pytest.raises(ValueError):
        parse_token_blob("nonsense")


def test_send_invitation_hits_the_current_endpoint():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["csrf"] = request.headers.get("csrf-token")
        seen["cookie"] = request.headers.get("cookie")
        return httpx.Response(200, json={"data": {"value": {}}})

    result = client_with(handler).send_invitation("ACoAAABBBCCC", "Hola")
    assert result.status == "sent"
    assert "verifyQuotaAndCreateV2" in seen["url"]
    assert seen["body"]["invitee"]["inviteeUnion"]["memberProfile"] == (
        "urn:li:fsd_profile:ACoAAABBBCCC"
    )
    assert seen["body"]["customMessage"] == "Hola"
    assert seen["csrf"] == "ajax:123"  # unquoted in the header
    assert "Mozilla" not in (seen["cookie"] or "")  # quoted in the cookie, no UA


def test_send_invitation_skips_bad_input():
    def handler(request):  # pragma: no cover - must not be called
        raise AssertionError("no request should be made")

    client = client_with(handler)
    assert client.send_invitation("").code == "EMPTY_VMID"
    assert client.send_invitation("julio-perez").code == "BAD_VMID"
    assert client.send_invitation("ACoAAABBBCCC", "x" * 301).code == "MESSAGE_TOO_LONG"


def test_rate_limit_is_retried_and_cools_down():
    result = client_with(lambda request: httpx.Response(429, json={"code": "TOO_MANY"}))
    result = result.send_invitation("ACoAAABBBCCC")
    assert result.status == "failed" and result.retry is True
    assert result.code == "RATE_LIMIT" and result.account_action == "cooldown"


def test_expired_session_flags_the_account():
    result = client_with(lambda request: httpx.Response(999, text="CSRF check failed"))
    result = result.send_invitation("ACoAAABBBCCC")
    assert result.account_action == "needs_reauth" and result.retry is True


def test_two_hundred_with_error_envelope_is_not_a_send():
    def handler(request):
        return httpx.Response(200, json={"status": 400, "code": "CANT_RESEND_YET"})

    result = client_with(handler).send_invitation("ACoAAABBBCCC")
    assert result.status == "skipped" and result.code == "ALREADY_INVITED"


def test_quota_error_stops_the_account_for_the_day():
    def handler(request):
        return httpx.Response(400, json={"code": "WEEKLY_INVITE_LIMIT_EXCEEDED"})

    result = client_with(handler).send_invitation("ACoAAABBBCCC")
    assert result.code == "QUOTA" and result.account_action == "stop_today"


def test_falls_back_to_the_legacy_endpoint():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "verifyQuotaAndCreateV2" in str(request.url):
            return httpx.Response(404, json={"code": "NOT_FOUND"})
        return httpx.Response(201)

    result = client_with(handler).send_invitation("ACoAAABBBCCC")
    assert result.status == "sent" and result.code == "OK_LEGACY"
    assert len(calls) == 2 and "normInvitations" in calls[1]


def test_check_session():
    ok = client_with(
        lambda request: httpx.Response(200, json={"included": [{"firstName": "Julio", "lastName": "P"}]})
    ).check_session()
    assert ok.ok and ok.name == "Julio P"

    expired = client_with(lambda request: httpx.Response(401)).check_session()
    assert not expired.ok and "expired" in expired.detail

    missing = LinkedInClient(tokens={"li_at": "x"}).check_session()
    assert not missing.ok and "JSESSIONID" in missing.detail


def test_classify_error_table():
    assert classify_error(503, "", "").retry is True
    assert classify_error(400, "SPAM_RESTRICTION", "").status == "failed"
    assert classify_error(400, "ALREADY_CONNECTED", "").status == "skipped"
