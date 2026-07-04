# Milestone 2 — Detailed Implementation Plan

**Goal:** parse a roster file (`.csv` or `.xlsx`) into validated `Student`
records, aggregate them into `Group`s, and wire `graider setup --roster … --dry-run`
to print the parsed groups as a table **without touching GitLab**.

This document is prescriptive. Follow the steps in order. Where full code is
given, you may copy it verbatim. Do not add features from later milestones (no
project creation, no invites — those are Milestones 3–5).

**Definition of done (verify all at the end):**

- `uv run graider setup --roster roster.csv --dry-run` prints a Rich table of
  groups + members and exits 0, with **no token required**.
- `.xlsx` rosters work the same way.
- Header aliases work: `E-Mail`/`Mail`, `Group`/`Team`/`Group Number` are all
  recognized; unknown columns are ignored.
- A roster with a bad email, a missing group, or a duplicate student fails with
  a clear message that names the **spreadsheet row number**.
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`, and
  `uv run pytest` all pass.

---

## Step 1 — Add the openpyxl dependency

`.csv` uses the stdlib; `.xlsx` needs openpyxl. Edit `pyproject.toml`, under
`[project]` change the `dependencies` list to add one line:

```toml
dependencies = [
    "typer>=0.12",
    "rich>=13.7",
    "pydantic>=2.7",
    "openpyxl>=3.1",
]
```

Then:

```sh
uv sync
```

---

## Step 2 — Target file layout

New/changed files this milestone:

```
src/graider/
├── errors.py     # + RosterError
├── models.py     # NEW: Student, Group
├── roster.py     # NEW: read_roster(), group_students()
├── console.py    # + print_groups()
└── cli.py        # setup gains --roster and prints the table
tests/
├── test_roster.py   # NEW
└── test_cli.py      # updated setup tests
```

---

## Step 3 — `errors.py`: add `RosterError`

Append one class (keep the existing ones):

```python
class RosterError(GraiderError):
    """The roster file is missing, malformed, or has invalid rows."""
```

---

## Step 4 — `src/graider/models.py` (NEW)

Pydantic models with normalization/validation baked into `Student`. Keeping the
validators here means `roster.py` can catch `ValidationError` per row and report
line numbers.

```python
"""Shared domain models."""

from __future__ import annotations

import re

from pydantic import BaseModel, field_validator

# Deliberately loose: this is a sanity check for roster typos, not RFC 5322.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Student(BaseModel):
    email: str
    group_number: str
    name: str | None = None

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not EMAIL_RE.match(value):
            raise ValueError(f"invalid email: {value!r}")
        return value

    @field_validator("group_number")
    @classmethod
    def _non_empty_group(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("missing group number")
        return value

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class Group(BaseModel):
    number: str
    members: list[Student]
```

> Emails are lowercased so duplicate detection is case-insensitive.
> `group_number` is a **string** on purpose — group ids may be `"1"`, `"01"`, or
> `"A"`, and they become part of project names later.

---

## Step 5 — `src/graider/roster.py` (NEW)

Reads `.csv`/`.xlsx` into `list[Student]`, mapping header aliases to canonical
fields, validating every row, and accumulating **all** errors before raising.

### Behavior

- Dispatch on file suffix: `.csv` → stdlib `csv`; `.xlsx`/`.xlsm` → openpyxl.
  Anything else → `RosterError`.
- Header row is spreadsheet **row 1**; data rows are numbered from **2** so
  error messages match what the user sees in Excel/LibreOffice.
- Required columns: an email column and a group column (matched via aliases).
  Missing either → `RosterError` naming what was searched for.
- Per-row validation collects errors (bad email, missing group, duplicate
  student) and raises them together, one per line, prefixed with `row N:`.
- Fully blank rows are skipped.

### Full code

```python
"""Roster parsing: CSV/XLSX -> validated Students -> Groups."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from openpyxl import load_workbook
from pydantic import ValidationError

from graider.errors import RosterError
from graider.models import Group, Student

# Canonical field -> accepted header names (after normalization: lowercased,
# runs of space/underscore/hyphen collapsed to a single space).
EMAIL_HEADERS = {"email", "e mail", "mail", "student email", "student e mail"}
GROUP_HEADERS = {"group", "group number", "groupnumber", "group no", "team", "team number"}
NAME_HEADERS = {"name", "student", "student name", "full name"}


def read_roster(path: Path) -> list[Student]:
    """Parse a roster file into validated Students. Raises RosterError."""
    if not path.exists():
        raise RosterError(f"Roster file not found: {path}")

    headers, raw_rows = _load_rows(path)
    field_by_col = _map_headers(headers, path)

    students: list[Student] = []
    errors: list[str] = []
    seen: dict[str, int] = {}

    for offset, raw in enumerate(raw_rows):
        rownum = offset + 2  # header is row 1
        row = {
            field: raw[col] if col < len(raw) else ""
            for col, field in field_by_col.items()
        }
        if not any(v.strip() for v in row.values()):
            continue  # blank row

        try:
            student = Student(
                email=row.get("email", ""),
                group_number=row.get("group_number", ""),
                name=row.get("name") or None,
            )
        except ValidationError as exc:
            for err in exc.errors():
                errors.append(f"row {rownum}: {err['msg']}")
            continue

        if student.email in seen:
            errors.append(
                f"row {rownum}: duplicate student {student.email} "
                f"(first seen row {seen[student.email]})"
            )
            continue
        seen[student.email] = rownum
        students.append(student)

    if errors:
        raise RosterError("Roster has problems:\n  " + "\n  ".join(errors))
    if not students:
        raise RosterError(f"No students found in {path}")
    return students


def group_students(students: list[Student]) -> list[Group]:
    """Aggregate students into groups, ordered by first appearance."""
    buckets: dict[str, list[Student]] = {}
    for student in students:
        buckets.setdefault(student.group_number, []).append(student)
    return [Group(number=number, members=members) for number, members in buckets.items()]


# --- internals ---------------------------------------------------------------


def _load_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        rows = _read_csv(path)
    elif suffix in (".xlsx", ".xlsm"):
        rows = _read_xlsx(path)
    else:
        raise RosterError(
            f"Unsupported roster format {path.suffix!r} (use .csv or .xlsx)"
        )
    if not rows:
        raise RosterError(f"{path} is empty")
    return rows[0], rows[1:]


def _read_csv(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return [[(cell or "").strip() for cell in row] for row in csv.reader(fh)]


def _read_xlsx(path: Path) -> list[list[str]]:
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.active
        return [
            [_cell_to_str(cell) for cell in row]
            for row in ws.iter_rows(values_only=True)
        ]
    finally:
        wb.close()


def _cell_to_str(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))  # 1.0 -> "1"
    return str(value).strip()


def _map_headers(headers: list[str], path: Path) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for col, header in enumerate(headers):
        field = _canonical_field(header)
        if field is not None:
            mapping[col] = field
    fields = set(mapping.values())
    if "email" not in fields:
        raise RosterError(
            f"{path}: no email column found (looked for {sorted(EMAIL_HEADERS)})"
        )
    if "group_number" not in fields:
        raise RosterError(
            f"{path}: no group column found (looked for {sorted(GROUP_HEADERS)})"
        )
    return mapping


def _canonical_field(header: str) -> str | None:
    key = re.sub(r"[\s_\-]+", " ", (header or "").strip().lower()).strip()
    if key in EMAIL_HEADERS:
        return "email"
    if key in GROUP_HEADERS:
        return "group_number"
    if key in NAME_HEADERS:
        return "name"
    return None
```

> `err['msg']` from pydantic v2 looks like `Value error, invalid email: 'x'`.
> That is acceptable for now — the row prefix is what matters for the user.

---

## Step 6 — `src/graider/console.py`: add `print_groups`

Append (and add the `Table` import at the top):

```python
from rich.table import Table

from graider.models import Group
```

```python
def print_groups(groups: list[Group]) -> None:
    table = Table(title="Roster")
    table.add_column("Group", style="bold")
    table.add_column("Members")
    table.add_column("#", justify="right")
    for group in groups:
        members = "\n".join(m.email for m in group.members)
        table.add_row(group.number, members, str(len(group.members)))
    console.print(table)
```

> `console.py` importing `models` is fine — `models` imports only pydantic, so
> there is no import cycle.

---

## Step 7 — `src/graider/cli.py`: wire `--roster` into `setup`

Add imports:

```python
from graider.console import console, print_error, print_groups, print_success
from graider.roster import group_students, read_roster
```

Replace the whole `setup` command with:

```python
@app.command()
def setup(
    ctx: typer.Context,
    roster: Path = typer.Option(
        ...,
        "--roster",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Path to the roster CSV/XLSX (student emails + group numbers).",
    ),
) -> None:
    """Create GitLab projects from a roster. (roster parsing only for now)"""
    config = _config(ctx)
    if not config.dry_run:
        require_token(config)  # fail fast before parsing on real runs

    students = read_roster(roster)
    groups = group_students(students)
    print_groups(groups)

    summary = f"{len(students)} students in {len(groups)} groups"
    if config.dry_run:
        print_success(f"{summary} (dry run, GitLab untouched).")
    else:
        print_success(f"{summary} — project creation not yet implemented.")
```

> `require_token` still raises `AuthError`; the top-level `run()` wrapper from
> Milestone 1 turns it into a clean message. Do not re-add a local try/except.
> `--roster` is required, so Typer rejects a missing/nonexistent file with its
> own usage error (exit 2) before the command body runs.

---

## Step 8 — Tests

### `tests/test_roster.py` (NEW)

```python
import pytest
from openpyxl import Workbook

from graider.errors import RosterError
from graider.models import Student
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
```

### `tests/test_cli.py` (UPDATE)

The Milestone 1 setup tests called `setup` with no `--roster`; that now fails
Typer validation. Add a roster fixture and update them, plus new dry-run tests.
Add near the top:

```python
def _roster(tmp_path):
    p = tmp_path / "roster.csv"
    p.write_text("email,group\na@x.edu,1\nb@x.edu,2\n")
    return str(p)
```

Update the existing setup tests to pass `--roster`:

- `test_setup_without_token_shows_url`: args become
  `[*_no_config(tmp_path), "--roster", _roster(tmp_path), "setup"]`; still
  expects exit 1 and the token URL (token check runs before parsing).
- `test_setup_with_token_env`: same `--roster` addition; still exit 0, and now
  assert `"not yet implemented"` **or** `"2 students"` appears.

Add:

```python
def test_setup_dry_run_prints_groups(tmp_path, monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    result = run_cli(
        [*_no_config(tmp_path), "--dry-run", "--roster", _roster(tmp_path), "setup"]
    )
    assert result.exit_code == 0            # no token needed for dry run
    assert "Roster" in result.output
    assert "a@x.edu" in result.output


def test_setup_bad_roster_reports_row(tmp_path, monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    bad = tmp_path / "bad.csv"
    bad.write_text("email,group\nnope,1\n")
    result = run_cli(
        [*_no_config(tmp_path), "--dry-run", "--roster", str(bad), "setup"]
    )
    assert result.exit_code == 1
    assert "row 2" in result.output
```

> If the `run_cli` harness renders Rich tables narrower than the emails, the
> `a@x.edu` assertion could fail on wrapping. If so, construct the console with
> a fixed width in tests, or assert on the group number (`"1"`) instead.

---

## Step 9 — Verify

```sh
uv sync
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest -q

# manual smoke test
printf 'email,group\nada@uni.edu,1\nbob@uni.edu,1\ncleo@uni.edu,2\n' > /tmp/roster.csv
uv run graider setup --roster /tmp/roster.csv --dry-run    # prints table, exit 0
uv run graider setup --roster /tmp/roster.csv              # no token -> clean URL error, exit 1
```

If `ruff format --check` fails, run `uv run ruff format .` and re-check.

---

## Notes for the next milestone

- `group_students()` returns `list[Group]` (ordered) rather than the raw
  `dict` sketched in the master plan — Milestone 3 consumes `Group` objects
  directly to create one project per group.
- `Student.group_number` is the join key between roster and projects; keep it a
  string end-to-end.
- The roster loader raises `RosterError` (a `GraiderError`), so the CLI shows a
  clean message automatically — no new error handling needed in `cli.py`.
- Email validation is intentionally loose. If real rosters need stricter checks,
  swap `EMAIL_RE` for pydantic's `EmailStr` (adds the `email-validator` dep) in
  a later pass — isolate that change to `models.py`.
```
