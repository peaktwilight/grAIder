# Milestone 9 — Detailed Implementation Plan

**Goal:** a teacher authoring workflow — `graider criteria init` drafts a
staggered-eval-ready criteria repo from a syllabus (via a structured Claude call),
and `graider criteria check` validates an existing criteria repo.

Builds on Milestone 7 (criteria format + parser) and Milestone 8 (anthropic SDK
+ structured output).

**Definition of done:**

- `graider criteria init --syllabus FILE --out DIR` writes `DIR/criteria.md`
  (brief stub + ordered items) and `DIR/graider-criteria.yml`
  (`released_up_to: 0`), drafted from the syllabus by the model.
- The generated `criteria.md` round-trips through Milestone 7's
  `load_criteria_dir` into ordered items with stable numeric IDs.
- `graider criteria check DIR` validates the repo (≥1 item, unique IDs, sequential
  order, a valid `graider-criteria.yml` cutoff) and reports problems or "OK".
- `criteria check` is pure logic (no network); `criteria init` mocks the client
  in tests. `ruff`, `ruff format --check`, `ty`, `pytest` pass.

---

## Step 1 — Dependencies

None new (`anthropic` from Milestone 8; PDF syllabi are sent as an anthropic
document content block — no extra parser).

---

## Step 2 — File layout

```
src/graider/
├── models.py             # + DraftItem, CriteriaDraft
├── authoring/
│   ├── __init__.py
│   └── criteria.py       # NEW: draft_criteria, write_criteria_dir, check_criteria_dir
├── console.py            # + print_check_report()
└── cli.py                # NEW `criteria` command group (init, check)
tests/
├── test_authoring.py     # NEW (check = pure; init mocks client)
```

---

## Step 3 — `models.py`: draft schemas

```python
class DraftItem(BaseModel):
    title: str
    body: str   # description + suggested evaluation questions for graders


class CriteriaDraft(BaseModel):
    brief: str
    items: list[DraftItem]
```

(Required fields, no defaults — forces the model to fill them.)

---

## Step 4 — `src/graider/authoring/criteria.py` (NEW)

### Behavior

- `draft_criteria(syllabus, model, client)` — read the syllabus (text file →
  text block; `.pdf` → base64 anthropic document block), call
  `client.messages.parse(..., output_format=CriteriaDraft)`, wrap SDK errors in
  `GraiderError` (same pattern as Milestone 8).
- `write_criteria_dir(draft, out_dir)` — render `criteria.md` (brief stub +
  `## N. Title` items, numbered from 1) and `graider-criteria.yml`
  (`released_up_to: 0`). Never overwrite a non-empty dir without `--force`.
- `check_criteria_dir(dir)` — load via Milestone 7's `load_criteria_dir`,
  return a list of problem strings (empty = valid).

### Code

```python
"""Teacher authoring: draft criteria from a syllabus, and validate a criteria repo."""

from __future__ import annotations

import base64
from pathlib import Path

import anthropic

from graider.criteria import load_criteria_dir, released_cutoff
from graider.errors import GraiderError
from graider.models import CriteriaDraft

DEFAULT_MODEL = "claude-opus-4-8"

_SYSTEM = (
    "You are a university teaching assistant. From the given syllabus, extract "
    "the topics students are graded on, in teaching order. Produce an ordered "
    "list of grading criteria: one item per topic, each with a short title and a "
    "body describing what to check plus 2-3 concrete evaluation questions a "
    "grader would ask. Also write a one-paragraph project brief."
)


def draft_criteria(
    syllabus: Path,
    *,
    model: str = DEFAULT_MODEL,
    client: anthropic.Anthropic | None = None,
) -> CriteriaDraft:
    if not syllabus.exists():
        raise GraiderError(f"Syllabus not found: {syllabus}")
    client = client or anthropic.Anthropic()
    content = _syllabus_content(syllabus)
    try:
        response = client.messages.parse(
            model=model,
            max_tokens=16000,
            system=_SYSTEM,
            messages=[{"role": "user", "content": content}],
            output_format=CriteriaDraft,
        )
    except Exception as exc:
        raise GraiderError(
            f"Criteria drafting failed ({exc}). Check your Anthropic credentials "
            "(set ANTHROPIC_API_KEY or run `ant auth login`)."
        ) from exc
    draft = response.parsed_output
    if draft is None or not draft.items:
        raise GraiderError("The model returned no criteria items.")
    return draft


def _syllabus_content(syllabus: Path) -> list[dict]:
    if syllabus.suffix.lower() == ".pdf":
        data = base64.standard_b64encode(syllabus.read_bytes()).decode("ascii")
        return [
            {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": data},
            },
            {"type": "text", "text": "Draft grading criteria from this syllabus."},
        ]
    text = syllabus.read_text(encoding="utf-8")
    return [{"type": "text", "text": f"Syllabus:\n\n{text}"}]


def write_criteria_dir(draft: CriteriaDraft, out_dir: Path, *, force: bool = False) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = out_dir / "criteria.md"
    cutoff = out_dir / "graider-criteria.yml"
    if not force and (doc.exists() or cutoff.exists()):
        raise GraiderError(f"{out_dir} already has criteria files; pass --force to overwrite.")

    lines = ["# Project Brief", "", draft.brief.strip(), "", "# Criteria", ""]
    for index, item in enumerate(draft.items, start=1):
        lines += [f"## {index}. {item.title.strip()}", "", item.body.strip(), ""]
    doc.write_text("\n".join(lines), encoding="utf-8")
    cutoff.write_text("released_up_to: 0\n", encoding="utf-8")


def check_criteria_dir(criteria_dir: Path) -> list[str]:
    problems: list[str] = []
    try:
        criteria = load_criteria_dir(criteria_dir)
    except GraiderError as exc:
        return [str(exc)]

    if not criteria.items:
        problems.append("no criteria items found")
    ids = [item.id for item in criteria.items]
    if len(ids) != len(set(ids)):
        problems.append(f"duplicate criteria ids: {sorted(i for i in ids if ids.count(i) > 1)}")
    for expected, item in enumerate(criteria.items, start=1):
        if item.order != expected:
            problems.append(f"item {item.id!r} has order {item.order}, expected {expected}")

    cutoff = released_cutoff(criteria_dir)
    if cutoff is None:
        problems.append("missing graider-criteria.yml (released_up_to)")
    elif str(cutoff).isdigit():
        if not (0 <= int(cutoff) <= len(criteria.items)):
            problems.append(f"released_up_to {cutoff} out of range 0..{len(criteria.items)}")
    elif str(cutoff) not in ids:
        problems.append(f"released_up_to {cutoff!r} matches no item id")
    return problems
```

---

## Step 5 — `console.py`: `print_check_report`

```python
def print_check_report(criteria_dir: Path, problems: list[str]) -> None:
    if not problems:
        print_success(f"{criteria_dir}: criteria OK")
        return
    err_console.print(f"[bold red]✗[/] {criteria_dir}: {len(problems)} problem(s)")
    for problem in problems:
        err_console.print(f"  • {problem}")
```

(Add `from pathlib import Path` if needed.)

---

## Step 6 — `cli.py`: the `criteria` command group

```python
from graider.authoring.criteria import (
    DEFAULT_MODEL as CRITERIA_MODEL,
    check_criteria_dir,
    draft_criteria,
    write_criteria_dir,
)
from graider.console import ..., print_check_report
```

```python
criteria_app = typer.Typer(help="Author and validate grading criteria.")
app.add_typer(criteria_app, name="criteria")


@criteria_app.command("init")
def criteria_init(
    syllabus: Path = typer.Option(..., "--syllabus", exists=True, dir_okay=False),
    out: Path = typer.Option(..., "--out", help="Criteria repo directory to create."),
    model: str = typer.Option(CRITERIA_MODEL, "--model"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Draft a staggered-eval criteria repo from a syllabus."""
    draft = draft_criteria(syllabus, model=model)
    write_criteria_dir(draft, out, force=force)
    print_success(f"Drafted {len(draft.items)} criteria → {out} (released_up_to: 0)")


@criteria_app.command("check")
def criteria_check(
    criteria_dir: Path = typer.Argument(..., exists=True, file_okay=False),
) -> None:
    """Validate a criteria repo (ids, order, cutoff)."""
    problems = check_criteria_dir(criteria_dir)
    print_check_report(criteria_dir, problems)
    if problems:
        raise typer.Exit(code=1)
```

> `criteria check` exits 1 on problems so it's usable in CI on the criteria repo.

---

## Step 7 — Tests (`tests/test_authoring.py`)

```python
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from graider.authoring.criteria import (
    check_criteria_dir, draft_criteria, write_criteria_dir,
)
from graider.criteria import load_criteria_dir
from graider.errors import GraiderError
from graider.models import CriteriaDraft, DraftItem


def _draft():
    return CriteriaDraft(
        brief="Build a library system.",
        items=[
            DraftItem(title="Version control", body="Uses git. Q: meaningful commits?"),
            DraftItem(title="Testing", body="Has tests. Q: coverage?"),
        ],
    )


def test_write_and_roundtrip(tmp_path):
    write_criteria_dir(_draft(), tmp_path)
    assert (tmp_path / "criteria.md").exists()
    assert (tmp_path / "graider-criteria.yml").read_text().strip() == "released_up_to: 0"
    criteria = load_criteria_dir(tmp_path)
    assert [i.id for i in criteria.items] == ["1", "2"]
    assert [i.title for i in criteria.items] == ["Version control", "Testing"]
    assert "Build a library system." in criteria.brief


def test_write_refuses_overwrite(tmp_path):
    write_criteria_dir(_draft(), tmp_path)
    with pytest.raises(GraiderError, match="already has criteria"):
        write_criteria_dir(_draft(), tmp_path)
    write_criteria_dir(_draft(), tmp_path, force=True)  # ok


def test_draft_criteria_mocked(tmp_path):
    syllabus = tmp_path / "syllabus.md"
    syllabus.write_text("Week 1: git. Week 2: testing.\n")
    client = MagicMock()
    client.messages.parse.return_value = MagicMock(parsed_output=_draft())
    draft = draft_criteria(syllabus, client=client)
    assert len(draft.items) == 2


def test_draft_wraps_sdk_errors(tmp_path):
    syllabus = tmp_path / "s.md"
    syllabus.write_text("x")
    client = MagicMock()
    client.messages.parse.side_effect = RuntimeError("401")
    with pytest.raises(GraiderError, match="Anthropic credentials"):
        draft_criteria(syllabus, client=client)


def test_check_valid(tmp_path):
    write_criteria_dir(_draft(), tmp_path)
    assert check_criteria_dir(tmp_path) == []


def test_check_flags_bad_cutoff(tmp_path):
    write_criteria_dir(_draft(), tmp_path)
    (tmp_path / "graider-criteria.yml").write_text("released_up_to: 9\n")
    problems = check_criteria_dir(tmp_path)
    assert any("out of range" in p for p in problems)


def test_check_missing_cutoff(tmp_path):
    (tmp_path / "criteria.md").write_text("# Brief\nx\n\n## 1. A\na\n")
    problems = check_criteria_dir(tmp_path)
    assert any("released_up_to" in p for p in problems)
```

---

## Step 8 — Verify

```sh
uv sync
uv run ruff check . && uv run ruff format --check . && uv run ty check
uv run pytest -q

# manual: draft check works offline on a hand-written repo
mkdir -p /tmp/c && printf '# Brief\nx\n\n## 1. A\na\n\n## 2. B\nb\n' > /tmp/c/criteria.md
printf 'released_up_to: 1\n' > /tmp/c/graider-criteria.yml
uv run graider criteria check /tmp/c        # → criteria OK
```

`criteria init` needs real credentials — smoke test with a small `syllabus.md`
and inspect the generated `criteria.md` / `graider-criteria.yml`.

---

## Notes for the next milestone

- The teacher scaffolds criteria here (`released_up_to: 0`), then advances the
  cutoff each week; Milestone 7's `review --up-to` / `released_up_to` consume it.
- The interactive "setup-assistant" skill mentioned in the master plan is better
  delivered as an E6 Claude Code skill (see `feature-requests-plan.md`) than as a
  bespoke prompt loop here — keep this milestone to `init` + `check`.
- **Milestone 10** (reports) is the last core piece: merge grade + review JSON
  into per-group reports.
```
