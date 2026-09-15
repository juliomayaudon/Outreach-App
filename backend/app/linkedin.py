"""LinkedIn Voyager client.

Same logic as the fixed Colab notebook, wrapped in a class and with the
responses classified so the worker knows whether to retry a row, skip it, or
stop the whole account.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import httpx

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Real browser cookies. Anything else in the token blob (user-agent,
# csrf-token) is a header: sending the user-agent as a cookie corrupts the
# Cookie header, because its value contains ";".
COOKIE_KEYS = ("li_at", "JSESSIONID", "li_a", "liap", "lidc", "bcookie", "bscookie", "li_rm")

INVITE_URL = (
    "https://www.linkedin.com/voyager/api/voyagerRelationshipsDashMemberRelationships"
    "?action=verifyQuotaAndCreateV2"
)
LEGACY_INVITE_URL = "https://www.linkedin.com/voyager/api/growth/normInvitations"
ME_URL = "https://www.linkedin.com/voyager/api/me"

MAX_MESSAGE_LENGTH = 300


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def normalize_profile_id(value: object) -> str:
    """Accepts ACoAA..., urn:li:fsd_profile:ACoAA... or a LinkedIn profile URL."""
    text = str(value or "").strip()
    if not text:
        return ""
    if "urn:li:" in text:
        text = text.rsplit(":", 1)[-1]
    if "linkedin.com" in text:
        text = text.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
    return text


def looks_like_vmid(value: str) -> bool:
    return value.startswith("AC") and len(value) >= 10


def build_cookies(tokens: dict) -> dict:
    cookies = {k: str(v) for k, v in tokens.items() if k in COOKIE_KEYS and v}
    session_id = cookies.get("JSESSIONID")
    if session_id and not session_id.startswith('"'):
        cookies["JSESSIONID"] = f'"{session_id}"'
    return cookies


def parse_token_blob(blob: str) -> dict:
    """Accepts the dict the notebook uses (single quotes) or plain JSON."""
    text = (blob or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    import ast

    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError) as error:
        raise ValueError(f"Could not read the tokens: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("The tokens must be a dictionary of cookies.")
    return {str(k): str(v) for k, v in value.items()}


# --------------------------------------------------------------------------
# results
# --------------------------------------------------------------------------
@dataclass
class SendResult:
    status: str  # sent | failed | skipped
    code: str = "OK"
    message: str = ""
    http_status: int | None = None
    retry: bool = False  # leave the row pending and try again later
    account_action: str = ""  # "" | needs_reauth | cooldown | stop_today


@dataclass
class SessionCheck:
    ok: bool
    name: str = ""
    detail: str = ""
    http_status: int | None = None


QUOTA_MARKERS = ("LIMIT", "QUOTA", "TOO_MANY", "EXCEEDED")
ALREADY_MARKERS = (
    "ALREADY_INVITED",
    "ALREADY_CONNECTED",
    "CANT_RESEND_YET",
    "INVITATION_ALREADY",
    "DUPLICATE",
)


def classify_error(http_status: int | None, code: str, message: str) -> SendResult:
    """Turns a LinkedIn error into an action for the worker."""
    haystack = f"{code} {message}".upper()

    if http_status in (401, 403, 999):
        return SendResult(
            status="failed",
            code="AUTH",
            message="LinkedIn rejected the session. Refresh li_at / JSESSIONID.",
            http_status=http_status,
            retry=True,
            account_action="needs_reauth",
        )
    if http_status == 429:
        return SendResult(
            status="failed",
            code="RATE_LIMIT",
            message="Rate limited by LinkedIn; backing off.",
            http_status=http_status,
            retry=True,
            account_action="cooldown",
        )
    if any(marker in haystack for marker in ALREADY_MARKERS):
        return SendResult(
            status="skipped",
            code="ALREADY_INVITED",
            message=message or "Already invited or already connected.",
            http_status=http_status,
        )
    if any(marker in haystack for marker in QUOTA_MARKERS):
        return SendResult(
            status="failed",
            code="QUOTA",
            message=message or "LinkedIn invitation quota reached.",
            http_status=http_status,
            retry=True,
            account_action="stop_today",
        )
    if http_status is not None and http_status >= 500:
        return SendResult(
            status="failed",
            code="SERVER_ERROR",
            message=message or f"LinkedIn returned {http_status}.",
            http_status=http_status,
            retry=True,
        )
    return SendResult(
        status="failed",
        code=code or "UNKNOWN",
        message=message or "Unknown error from LinkedIn.",
        http_status=http_status,
    )


def _describe(response: httpx.Response) -> tuple[str, str]:
    """(code, message) out of a Voyager error body."""
    try:
        data = response.json()
    except ValueError:
        return "", (response.text or "")[:300]
    if isinstance(data, dict):
        code = str(data.get("code") or "")
        message = str(data.get("message") or data.get("errorDetails") or "")
        if not (code or message):
            message = json.dumps(data)[:300]
        return code, message[:300]
    return "", str(data)[:300]


# --------------------------------------------------------------------------
# client
# --------------------------------------------------------------------------
@dataclass
class LinkedInClient:
    tokens: dict
    user_agent: str = DEFAULT_USER_AGENT
    timeout: float = 30.0
    transport: httpx.BaseTransport | None = None
    cookies: dict = field(init=False)

    def __post_init__(self) -> None:
        self.cookies = build_cookies(self.tokens)
        self.user_agent = self.user_agent or DEFAULT_USER_AGENT
        csrf = str(self.tokens.get("csrf-token") or self.tokens.get("JSESSIONID") or "")
        self._headers = {
            "csrf-token": csrf.strip().strip('"'),
            "user-agent": self.user_agent,
            "x-restli-protocol-version": "2.0.0",
            "accept-language": "en-AU,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
            "x-li-lang": "en_US",
            "accept": "application/vnd.linkedin.normalized+json+2.1",
            "referer": "https://www.linkedin.com/feed/",
            "origin": "https://www.linkedin.com",
        }

    @property
    def missing_cookies(self) -> list[str]:
        return [key for key in ("li_at", "JSESSIONID") if not self.cookies.get(key)]

    def _client(self) -> httpx.Client:
        return httpx.Client(
            headers=self._headers,
            cookies=self.cookies,
            timeout=self.timeout,
            transport=self.transport,
            follow_redirects=False,
        )

    # -- session -----------------------------------------------------------
    def check_session(self) -> SessionCheck:
        missing = self.missing_cookies
        if missing:
            return SessionCheck(False, detail="Missing cookies: " + ", ".join(missing))
        try:
            with self._client() as client:
                response = client.get(ME_URL)
        except httpx.HTTPError as error:
            return SessionCheck(False, detail=f"Could not reach LinkedIn: {error}")

        if response.status_code == 200:
            name = ""
            try:
                for item in response.json().get("included") or []:
                    if item.get("firstName"):
                        name = f"{item.get('firstName', '')} {item.get('lastName', '')}".strip()
                        break
            except ValueError:
                pass
            return SessionCheck(True, name=name, http_status=200)

        if response.status_code in (401, 403, 999):
            return SessionCheck(
                False,
                detail="Session rejected: the cookies expired or the csrf-token does "
                "not match JSESSIONID.",
                http_status=response.status_code,
            )
        code, message = _describe(response)
        return SessionCheck(
            False,
            detail=f"Unexpected answer ({response.status_code}) {code} {message}".strip(),
            http_status=response.status_code,
        )

    # -- invitations -------------------------------------------------------
    def send_invitation(self, profile_id: str, message: str = "") -> SendResult:
        profile_id = normalize_profile_id(profile_id)
        if not profile_id:
            return SendResult(status="skipped", code="EMPTY_VMID", message="Empty vmid.")
        if not looks_like_vmid(profile_id):
            return SendResult(
                status="skipped",
                code="BAD_VMID",
                message=f"'{profile_id}' is not a vmid (it should start with ACoAA...).",
            )
        message = (message or "").strip()
        if len(message) > MAX_MESSAGE_LENGTH:
            return SendResult(
                status="skipped",
                code="MESSAGE_TOO_LONG",
                message=f"The note is {len(message)} characters, the maximum is "
                f"{MAX_MESSAGE_LENGTH}.",
            )

        payload: dict = {
            "invitee": {"inviteeUnion": {"memberProfile": f"urn:li:fsd_profile:{profile_id}"}}
        }
        if message:
            payload["customMessage"] = message

        try:
            with self._client() as client:
                response = client.post(
                    INVITE_URL,
                    content=json.dumps(payload),
                    headers={"content-type": "application/json; charset=UTF-8"},
                )
        except httpx.HTTPError as error:
            return SendResult(
                status="failed",
                code="NETWORK",
                message=str(error)[:300],
                retry=True,
            )

        if response.status_code in (200, 201):
            # This endpoint answers 200 even for some business errors.
            try:
                data = response.json()
            except ValueError:
                data = None
            if isinstance(data, dict) and isinstance(data.get("status"), int):
                if data["status"] >= 400:
                    code, message_text = _describe(response)
                    return classify_error(data["status"], code, message_text)
            return SendResult(status="sent", code="OK", http_status=response.status_code)

        if response.status_code in (404, 405, 410):
            return self._send_invitation_legacy(profile_id, message)

        code, message_text = _describe(response)
        return classify_error(response.status_code, code, message_text)

    def _send_invitation_legacy(self, profile_id: str, message: str) -> SendResult:
        """Old endpoint, kept only in case the current one moves again."""
        import base64
        import random

        tracking_id = base64.b64encode(
            bytearray(random.randrange(256) for _ in range(16))
        ).decode()
        payload = {
            "trackingId": tracking_id,
            "message": message,
            "invitations": [],
            "excludeInvitations": [],
            "invitee": {
                "com.linkedin.voyager.growth.invitation.InviteeProfile": {
                    "profileId": profile_id
                }
            },
        }
        try:
            with self._client() as client:
                response = client.post(
                    LEGACY_INVITE_URL,
                    content=json.dumps(payload),
                    headers={"content-type": "application/json; charset=UTF-8"},
                )
        except httpx.HTTPError as error:
            return SendResult(status="failed", code="NETWORK", message=str(error)[:300], retry=True)

        if response.status_code in (200, 201):
            return SendResult(
                status="sent", code="OK_LEGACY", http_status=response.status_code
            )
        code, message_text = _describe(response)
        return classify_error(response.status_code, code, message_text)
