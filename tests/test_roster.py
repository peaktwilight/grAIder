import pytest
from openpyxl import Workbook

from graider.errors import RosterError
from graider.roster import group_students, read_roster


def _csv(tmp_path, text):
    p = tmp_path / "roster.csv"
    p.write_text(text)
    return p


def _xlsx(tmp_path, rows):
    p = tmp_path / "roster.xlsx"
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    wb.save(p)
    return p


def test_read_csv_basic(tmp_path):
    path = _csv(tmp_path, "email,group\na@x.edu,1\nb@x.edu,2\n")
    students = read_roster(path)
    assert [s.email for s in students] == ["a@x.edu", "b@x.edu"]
    assert [s.group_number for s in students] == ["1", "2"]


def test_read_xlsx_basic(tmp_path):
    path = _xlsx(tmp_path, [["email", "group"], ["a@x.edu", 1], ["b@x.edu", 2]])
    students = read_roster(path)
    assert [s.email for s in students] == ["a@x.edu", "b@x.edu"]
    # numeric group cell 1 -> "1", not "1.0"
    assert students[0].group_number == "1"


def test_header_aliases(tmp_path):
    path = _csv(tmp_path, "E-Mail,Team\nA@X.edu,7\n")
    students = read_roster(path)
    assert students[0].email == "a@x.edu"  # lowercased
    assert students[0].group_number == "7"


def test_extra_columns_ignored(tmp_path):
    path = _csv(tmp_path, "email,group,notes\na@x.edu,1,hello\n")
    students = read_roster(path)
    assert students[0].email == "a@x.edu"


def test_name_column_captured(tmp_path):
    path = _csv(tmp_path, "name,email,group\nAda,a@x.edu,1\n")
    assert read_roster(path)[0].name == "Ada"


def test_missing_email_column_raises(tmp_path):
    path = _csv(tmp_path, "group,notes\n1,hi\n")
    with pytest.raises(RosterError, match="no email column"):
        read_roster(path)


def test_bad_email_reports_row(tmp_path):
    path = _csv(tmp_path, "email,group\ngood@x.edu,1\nnope,2\n")
    with pytest.raises(RosterError, match="row 3"):
        read_roster(path)


def test_missing_group_reports_row(tmp_path):
    path = _csv(tmp_path, "email,group\na@x.edu,\n")
    with pytest.raises(RosterError, match="row 2"):
        read_roster(path)


def test_duplicate_student_raises(tmp_path):
    path = _csv(tmp_path, "email,group\na@x.edu,1\nA@X.edu,2\n")
    with pytest.raises(RosterError, match="duplicate"):
        read_roster(path)


def test_blank_rows_skipped(tmp_path):
    path = _csv(tmp_path, "email,group\na@x.edu,1\n,\nb@x.edu,2\n")
    assert len(read_roster(path)) == 2


def test_unsupported_extension_raises(tmp_path):
    p = tmp_path / "roster.txt"
    p.write_text("email,group\na@x.edu,1\n")
    with pytest.raises(RosterError, match="Unsupported"):
        read_roster(p)


def test_missing_file_raises(tmp_path):
    with pytest.raises(RosterError, match="not found"):
        read_roster(tmp_path / "nope.csv")


def test_group_aggregation_order(tmp_path):
    path = _csv(
        tmp_path,
        "email,group\na@x.edu,2\nb@x.edu,1\nc@x.edu,2\n",
    )
    groups = group_students(read_roster(path))
    assert [g.number for g in groups] == ["2", "1"]  # first appearance
    assert [m.email for m in groups[0].members] == ["a@x.edu", "c@x.edu"]
