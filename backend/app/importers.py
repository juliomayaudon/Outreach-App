"""Turning a CSV file or a Google Sheet into queued invitations."""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from .linkedin import looks_like_vmid, normalize_profile_id

PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")
MAX_MESSAGE_LENGTH = 300


class ImportError_(Exception):
    """Bad file the user can fix."""


@dataclass
class TableData:
    headers: list[str]
    rows: list[dict]
    row_numbers: list[int] = field(default_factory=list)


def parse_csv(data: bytes) -> TableData:
    if not data:
        raise ImportError_("The file is empty.")
    text = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ImportError_("Could not read the file, try saving it as UTF-8 CSV.")

    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        raw_rows = list(reader)
    except csv.Error as error:
        raise ImportError_(f"Malformed CSV: {error}") from error
    if not raw_rows:
        raise ImportError_("The file has no rows.")

    headers = [str(h).strip() for h in raw_rows[0]]
    if not any(headers):
        raise ImportError_("The first row must contain the column names.")

    rows: list[dict] = []
    row_numbers: list[int] = []
    for index, raw_row in enumerate(raw_rows[1:], start=2):
        if not any(str(cell).strip() for cell in raw_row):
            continue
        padded = list(raw_row) + [""] * (len(headers) - len(raw_row))
        rows.append(
            {headers[i]: str(padded[i]).strip() for i in range(len(headers)) if headers[i]}
        )
        row_numbers.append(index)
    return TableData(headers=[h for h in headers if h], rows=rows, row_numbers=row_numbers)


def guess_column(headers: list[str], candidates: tuple[str, ...]) -> str:
    """Best-effort mapping so the user does not have to pick every column."""
    lowered = {h.lower().strip(): h for h in headers}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    for candidate in candidates:
        for low, original in lowered.items():
            if candidate in low:
                return original
    return ""


def suggest_mapping(headers: list[str]) -> dict:
    return {
        "vmid": guess_column(headers, ("vmid", "profile_id", "profileid", "urn", "profile url", "profile")),
        "full_name": guess_column(headers, ("full name", "fullname", "name", "nombre", "contact")),
        "first_name": guess_column(headers, ("first name", "firstname", "first")),
        "company": guess_column(headers, ("company", "account", "empresa", "organization")),
        "title": guess_column(headers, ("title", "job title", "position", "cargo", "headline")),
        "message": guess_column(headers, ("message", "note", "mensaje", "nota")),
    }


def render_template(template: str, row: dict, mapping: dict) -> str:
    """Fills {first_name} / {full_name} / {company} / {title} from the row."""
    if not template:
        return ""

    def value_for(field_name: str) -> str:
        column = mapping.get(field_name) or ""
        if column and column in row:
            return str(row[column] or "").strip()
        return ""

    full_name = value_for("full_name")
    first_name = value_for("first_name") or (full_name.split(" ")[0] if full_name else "")
    values = {
        "first_name": first_name,
        "full_name": full_name,
        "name": full_name or first_name,
        "company": value_for("company"),
        "title": value_for("title"),
    }

    def replace(match: re.Match) -> str:
        return values.get(match.group(1), match.group(0))

    return PLACEHOLDER_RE.sub(replace, template).strip()


@dataclass
class PreparedRow:
    profile_id: str
    raw_value: str
    full_name: str = ""
    company: str = ""
    title: str = ""
    message: str = ""
    sheet_row: int | None = None
    status: str = "pending"  # pending | skipped
    error_code: str = ""
    error_message: str = ""


@dataclass
class PreparedBatch:
    rows: list[PreparedRow]

    @property
    def queued(self) -> int:
        return sum(1 for r in self.rows if r.status == "pending")

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.rows if r.status == "skipped")


def prepare_rows(
    table: TableData,
    mapping: dict,
    note_template: str = "",
    known_profile_ids: set[str] | None = None,
) -> PreparedBatch:
    """Normalises vmids, renders notes and flags what cannot be sent.

    known_profile_ids: profiles this LinkedIn account already has a row for,
    so the same person is never invited twice.
    """
    vmid_column = mapping.get("vmid")
    if not vmid_column:
        raise ImportError_("Pick the column that holds the vmid.")
    if vmid_column not in table.headers:
        raise ImportError_(
            f"The column '{vmid_column}' is not in the file. "
            f"Columns found: {', '.join(table.headers)}"
        )

    known = set(known_profile_ids or ())
    seen: set[str] = set()
    message_column = mapping.get("message") or ""
    prepared: list[PreparedRow] = []

    for index, row in enumerate(table.rows):
        raw_value = str(row.get(vmid_column, "") or "").strip()
        sheet_row = table.row_numbers[index] if index < len(table.row_numbers) else None
        profile_id = normalize_profile_id(raw_value)

        def field(name: str) -> str:
            column = mapping.get(name) or ""
            return str(row.get(column, "") or "").strip() if column else ""

        full_name = field("full_name")
        if not full_name and field("first_name"):
            full_name = field("first_name")

        item = PreparedRow(
            profile_id=profile_id,
            raw_value=raw_value,
            full_name=full_name[:160],
            company=field("company")[:160],
            title=field("title")[:200],
            sheet_row=sheet_row,
        )

        if not raw_value:
            continue  # genuinely empty row, not worth queueing
        if not looks_like_vmid(profile_id):
            item.status = "skipped"
            item.error_code = "BAD_VMID"
            item.error_message = f"'{raw_value}' is not a vmid (it should start with ACoAA...)."
            prepared.append(item)
            continue
        if profile_id in seen:
            item.status = "skipped"
            item.error_code = "DUPLICATE_IN_FILE"
            item.error_message = "Repeated in this file."
            prepared.append(item)
            continue
        if profile_id in known:
            item.status = "skipped"
            item.error_code = "ALREADY_QUEUED"
            item.error_message = "This account already has a row for this profile."
            prepared.append(item)
            continue

        message = ""
        if message_column and message_column in row:
            message = str(row.get(message_column, "") or "").strip()
        if not message:
            message = render_template(note_template, row, mapping)
        if len(message) > MAX_MESSAGE_LENGTH:
            item.status = "skipped"
            item.error_code = "MESSAGE_TOO_LONG"
            item.error_message = (
                f"The note is {len(message)} characters, the maximum is {MAX_MESSAGE_LENGTH}."
            )
            prepared.append(item)
            continue

        item.message = message
        seen.add(profile_id)
        prepared.append(item)

    return PreparedBatch(rows=prepared)
