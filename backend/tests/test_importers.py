import pytest

from app.importers import ImportError_, parse_csv, prepare_rows, render_template, suggest_mapping

CSV = (
    b"Full Name;vmid;Company;Job Title\n"
    b"Julio Perez;ACoAAA0001;Kalungi;CTO\n"
    b"Ana Diaz;https://www.linkedin.com/in/ACoAAA0002/;Acme;CEO\n"
    b"Bad Row;julio-perez;X;Y\n"
    b"Repeat;ACoAAA0001;Kalungi;CTO\n"
    b";;;\n"
)


def test_parse_csv_detects_delimiter_and_skips_blank_rows():
    table = parse_csv(CSV)
    assert table.headers == ["Full Name", "vmid", "Company", "Job Title"]
    assert len(table.rows) == 4
    assert table.row_numbers == [2, 3, 4, 5]  # 1-based, header is row 1


def test_parse_csv_handles_bom_and_latin1():
    assert parse_csv("vmid\nACoAAA1\n".encode("utf-8-sig")).headers == ["vmid"]
    assert parse_csv("name,vmid\nJosé,ACoAAA1\n".encode("latin-1")).rows[0]["name"] == "José"


def test_parse_csv_rejects_empty_input():
    with pytest.raises(ImportError_):
        parse_csv(b"")


def test_suggest_mapping_matches_common_headers():
    mapping = suggest_mapping(["Full Name", "vmid", "Company", "Job Title"])
    assert mapping["vmid"] == "vmid"
    assert mapping["full_name"] == "Full Name"
    assert mapping["company"] == "Company"
    assert mapping["title"] == "Job Title"


def test_render_template_fills_placeholders():
    row = {"Full Name": "Julio Perez", "Company": "Kalungi", "Job Title": "CTO"}
    mapping = {"full_name": "Full Name", "company": "Company", "title": "Job Title"}
    text = render_template("Hola {first_name}, vi que sos {title} en {company}.", row, mapping)
    assert text == "Hola Julio, vi que sos CTO en Kalungi."
    # Unknown placeholders are left alone instead of crashing.
    assert render_template("Hi {unknown}", row, mapping) == "Hi {unknown}"


def test_prepare_rows_flags_bad_vmids_and_duplicates():
    table = parse_csv(CSV)
    batch = prepare_rows(table, suggest_mapping(table.headers))
    assert batch.queued == 2
    codes = sorted(r.error_code for r in batch.rows if r.status == "skipped")
    assert codes == ["BAD_VMID", "DUPLICATE_IN_FILE"]
    assert batch.rows[1].profile_id == "ACoAAA0002"  # URL normalised


def test_prepare_rows_skips_profiles_the_account_already_has():
    table = parse_csv(CSV)
    batch = prepare_rows(table, suggest_mapping(table.headers), known_profile_ids={"ACoAAA0001"})
    assert batch.queued == 1
    assert any(r.error_code == "ALREADY_QUEUED" for r in batch.rows)


def test_prepare_rows_rejects_long_notes():
    table = parse_csv(b"vmid\nACoAAA0001\n")
    batch = prepare_rows(table, {"vmid": "vmid"}, note_template="x" * 301)
    assert batch.queued == 0
    assert batch.rows[0].error_code == "MESSAGE_TOO_LONG"


def test_prepare_rows_needs_a_vmid_column():
    table = parse_csv(b"name\nJulio\n")
    with pytest.raises(ImportError_):
        prepare_rows(table, {"vmid": ""})
    with pytest.raises(ImportError_):
        prepare_rows(table, {"vmid": "missing_column"})
