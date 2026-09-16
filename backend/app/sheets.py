"""Google Sheets access (same service account flow as the notebook, but the
credentials come from an environment variable instead of being hardcoded)."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from .config import get_settings

logger = logging.getLogger("sheets")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


class SheetError(Exception):
    """Something the user can fix: wrong URL, tab, or missing share."""


@dataclass
class SheetData:
    headers: list[str]
    rows: list[dict]
    row_numbers: list[int]  # 1-based row number in the sheet for each row


def sheets_enabled() -> bool:
    return bool(get_settings().google_service_account_json.strip())


def credentials_problem() -> str | None:
    """Why the configured key cannot be used, or None when it looks usable.

    Checked up front so a broken key shows a message the reader can act on,
    instead of a 500 from deep inside google-auth on the first sheet read.
    """
    raw = get_settings().google_service_account_json.strip()
    if not raw:
        return None  # not configured at all; a different message covers that
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as error:
        return (
            f"GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON: {error}. Paste the whole key "
            "file Google gave you, opening and closing braces included."
        )
    if not isinstance(info, dict) or not info.get("private_key"):
        return (
            "GOOGLE_SERVICE_ACCOUNT_JSON does not look like a service account key: "
            "it has no private_key field."
        )
    return None


def _repaired(info: dict) -> dict:
    """Undo newlines that were escaped twice on the way into the variable.

    Pasting a key through a notebook, a shell or a CI form turns the JSON
    escape \n into a literal backslash followed by n, and google-auth then
    cannot read the value as PEM. A correctly pasted key contains no
    backslashes in private_key at all, so this is a no-op for one.
    """
    key = info.get("private_key")
    if isinstance(key, str) and "\\n" in key:
        logger.info("Repaired double-escaped newlines in the service account private_key.")
        return {**info, "private_key": key.replace("\\n", "\n")}
    return info


def service_account_email() -> str:
    raw = get_settings().google_service_account_json.strip()
    if not raw:
        return ""
    try:
        return json.loads(raw).get("client_email", "")
    except json.JSONDecodeError:
        return ""


def _client():
    raw = get_settings().google_service_account_json.strip()
    if not raw:
        raise SheetError(
            "Google Sheets is not configured: set GOOGLE_SERVICE_ACCOUNT_JSON."
        )
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SheetError(f"GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON: {error}") from error

    import gspread
    from google.oauth2.service_account import Credentials

    try:
        credentials = Credentials.from_service_account_info(_repaired(info), scopes=SCOPES)
    except ValueError as error:
        # Most often a PEM that will not parse, which google-auth reports as a
        # bare ValueError. Left uncaught it surfaces as a 500 with no clue.
        raise SheetError(
            credentials_problem() or f"The service account key could not be loaded: {error}"
        ) from error
    return gspread.authorize(credentials)


def _open_worksheet(url: str, tab: str):
    import gspread

    if not re.search(r"/d/([a-zA-Z0-9-_]+)", url or ""):
        raise SheetError("That does not look like a Google Sheets URL.")
    try:
        spreadsheet = _client().open_by_url(url)
    except gspread.exceptions.SpreadsheetNotFound as error:
        raise SheetError(
            "Spreadsheet not found. Share it as Editor with "
            f"{service_account_email() or 'the service account'}."
        ) from error
    except gspread.exceptions.APIError as error:
        raise SheetError(
            "Google rejected the request. Make sure the sheet is shared as Editor with "
            f"{service_account_email() or 'the service account'}. ({error})"
        ) from error
    try:
        return spreadsheet.worksheet(tab) if tab else spreadsheet.sheet1
    except gspread.exceptions.WorksheetNotFound as error:
        available = ", ".join(ws.title for ws in spreadsheet.worksheets())
        raise SheetError(f"Tab '{tab}' not found. Tabs available: {available}") from error


def list_tabs(url: str) -> list[str]:
    import gspread

    try:
        return [ws.title for ws in _client().open_by_url(url).worksheets()]
    except gspread.exceptions.SpreadsheetNotFound as error:
        raise SheetError(
            "Spreadsheet not found. Share it as Editor with "
            f"{service_account_email() or 'the service account'}."
        ) from error
    except gspread.exceptions.APIError as error:
        raise SheetError(f"Google rejected the request: {error}") from error


def read_rows(url: str, tab: str = "") -> SheetData:
    worksheet = _open_worksheet(url, tab)
    values = worksheet.get_all_values()
    if not values:
        raise SheetError("That tab is empty.")
    headers = [str(h).strip() for h in values[0]]
    rows: list[dict] = []
    row_numbers: list[int] = []
    for index, raw_row in enumerate(values[1:], start=2):
        padded = list(raw_row) + [""] * (len(headers) - len(raw_row))
        rows.append({headers[i]: padded[i] for i in range(len(headers)) if headers[i]})
        row_numbers.append(index)
    return SheetData(headers=[h for h in headers if h], rows=rows, row_numbers=row_numbers)


def write_results(url: str, tab: str, result_column: str, updates: list[tuple[int, str]]) -> int:
    """updates = [(sheet_row_number, text)]. Creates the column if missing."""
    if not updates:
        return 0
    import gspread

    worksheet = _open_worksheet(url, tab)
    header = [str(h).strip() for h in worksheet.row_values(1)]
    try:
        if result_column in header:
            column_index = header.index(result_column) + 1
        else:
            column_index = len(header) + 1
            # A sheet only accepts writes inside its existing grid. On a tab
            # whose columns are all used the new results column falls outside
            # it, and Google answers "exceeds grid limits" on every attempt,
            # forever, because nothing about the next try is different.
            if column_index > worksheet.col_count:
                worksheet.add_cols(column_index - worksheet.col_count)
            worksheet.update_cell(1, column_index, result_column)

        highest_row = max(row for row, _ in updates)
        if highest_row > worksheet.row_count:
            worksheet.add_rows(highest_row - worksheet.row_count)

        worksheet.update_cells(
            [gspread.Cell(row, column_index, value) for row, value in updates]
        )
    except gspread.exceptions.APIError as error:
        raise SheetError(f"Could not write the results back: {error}") from error
    return len(updates)
