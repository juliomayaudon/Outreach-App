"""Service account key handling.

The keys people actually paste arrive mangled in a few predictable ways, and
every one of them used to surface as a 500 from inside google-auth.
"""
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.oauth2.service_account import Credentials

from app import sheets
from app.config import get_settings

EMAIL = "robot@a-project.iam.gserviceaccount.com"


@pytest.fixture(scope="module")
def pem() -> str:
    """A real PEM, so the assertions go through google-auth rather than a stub."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def account(private_key: str) -> dict:
    return {
        "type": "service_account",
        "project_id": "a-project",
        "private_key_id": "abc123",
        "private_key": private_key,
        "client_email": EMAIL,
        "client_id": "1",
        "token_uri": "https://oauth2.googleapis.com/token",
    }


@pytest.fixture
def configure(monkeypatch):
    def set_value(value: str) -> None:
        monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", value)
        get_settings.cache_clear()

    yield set_value
    get_settings.cache_clear()


def test_a_key_escaped_twice_is_rejected_by_google_but_loads_once_repaired(pem):
    info = account(pem.replace("\n", "\\n"))

    with pytest.raises(ValueError):
        Credentials.from_service_account_info(info, scopes=sheets.SCOPES)

    credentials = Credentials.from_service_account_info(
        sheets._repaired(info), scopes=sheets.SCOPES
    )
    assert credentials.service_account_email == EMAIL


def test_a_correctly_pasted_key_is_left_untouched(pem):
    info = account(pem)
    assert sheets._repaired(info) == info


def test_the_object_pasted_without_its_braces_is_named_as_bad_json(configure):
    configure('"type": "service_account", "project_id": "a-project"')
    problem = sheets.credentials_problem()
    assert problem and "not valid JSON" in problem
    assert "braces" in problem


def test_something_that_is_not_a_key_at_all_is_named(configure):
    configure(json.dumps({"type": "service_account", "client_email": EMAIL}))
    problem = sheets.credentials_problem()
    assert problem and "no private_key" in problem


def test_unset_is_not_a_problem_because_a_separate_notice_covers_it(configure):
    configure("")
    assert sheets.credentials_problem() is None
    assert sheets.sheets_enabled() is False


def test_a_usable_key_reports_no_problem_and_exposes_its_address(configure, pem):
    configure(json.dumps(account(pem)))
    assert sheets.credentials_problem() is None
    assert sheets.sheets_enabled() is True
    assert sheets.service_account_email() == EMAIL


def test_an_escaped_key_reports_no_problem_since_it_is_repaired_on_use(configure, pem):
    configure(json.dumps(account(pem.replace("\n", "\\n"))))
    assert sheets.credentials_problem() is None
    assert sheets.service_account_email() == EMAIL
