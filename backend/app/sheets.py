"""Google Sheets access (same service account flow as the notebook, but the
credentials come from an environment variable instead of being hardcoded)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .config import get_settings

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

    credentials = Credentials.from_service_account_info(info, scopes=SCOPES)
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
    header = worksheet.row_values(1)
    header = [str(h).strip() for h in header]
    if result_column in header:
        column_index = header.index(result_column) + 1
    else:
        column_index = len(header) + 1
        worksheet.update_cell(1, column_index, result_column)

    cells = [gspread.Cell(row, column_index, value) for row, value in updates]
    try:
        worksheet.update_cells(cells)
    except gspread.exceptions.APIError as error:
        raise SheetError(f"Could not write the results back: {error}") from error
    return len(cells)
