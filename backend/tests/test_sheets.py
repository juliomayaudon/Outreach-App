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


# --------------------------------------------------------------------------
# writing the results column back
#
# The tab that broke this in production had every column in its grid used, so
# the new Result column landed outside it and Google refused the write with
# "exceeds grid limits" on every tick, forever.
# --------------------------------------------------------------------------
class FakeWorksheet:
    def __init__(self, header, col_count, row_count):
        self.header = header
        self.col_count = col_count
        self.row_count = row_count
        self.added_cols = 0
        self.added_rows = 0
        self.header_written = None
        self.cells = []

    def row_values(self, _row):
        return list(self.header)

    def add_cols(self, n):
        self.col_count += n
        self.added_cols += n

    def add_rows(self, n):
        self.row_count += n
        self.added_rows += n

    def update_cell(self, row, col, value):
        if col > self.col_count or row > self.row_count:
            raise AssertionError(f"wrote outside the grid at {row},{col}")
        self.header_written = (row, col, value)

    def update_cells(self, cells):
        for cell in cells:
            if cell.col > self.col_count or cell.row > self.row_count:
                raise AssertionError(f"wrote outside the grid at {cell.row},{cell.col}")
        self.cells = cells


@pytest.fixture
def worksheet(monkeypatch):
    def use(sheet):
        monkeypatch.setattr(sheets, "_open_worksheet", lambda url, tab: sheet)
        return sheet

    return use


def test_a_full_grid_is_grown_before_the_results_column_is_written(worksheet):
    sheet = worksheet(FakeWorksheet(header=["a"] * 518, col_count=518, row_count=3))

    written = sheets.write_results("url", "Test", "Result", [(2, "sent"), (3, "sent")])

    assert written == 2
    assert sheet.added_cols == 1, "the grid was not grown, so the write lands outside it"
    assert sheet.header_written == (1, 519, "Result")
    assert [c.col for c in sheet.cells] == [519, 519]


def test_a_grid_with_room_is_left_alone(worksheet):
    sheet = worksheet(FakeWorksheet(header=["a", "b"], col_count=26, row_count=100))

    sheets.write_results("url", "Test", "Result", [(2, "sent")])

    assert sheet.added_cols == 0
    assert sheet.added_rows == 0
    assert sheet.header_written == (1, 3, "Result")


def test_an_existing_results_column_is_reused_not_appended(worksheet):
    sheet = worksheet(FakeWorksheet(header=["a", "Result", "b"], col_count=26, row_count=100))

    sheets.write_results("url", "Test", "Result", [(2, "sent")])

    assert sheet.header_written is None, "it rewrote a header that was already there"
    assert [c.col for c in sheet.cells] == [2]


def test_rows_beyond_the_grid_are_added_too(worksheet):
    sheet = worksheet(FakeWorksheet(header=["a"], col_count=26, row_count=3))

    sheets.write_results("url", "Test", "Result", [(9, "sent")])

    assert sheet.added_rows == 6
    assert [c.row for c in sheet.cells] == [9]
