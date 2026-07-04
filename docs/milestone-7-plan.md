# Milestone 7 — Detailed Implementation Plan

**Goal:** load a course's grading criteria (Markdown or AsciiDoc) as an **ordered
list of items with stable IDs**, support **staggered evaluation** (evaluate only
up to a released cutoff), and make `graider review --dry-run` show which items
are in and out of scope. The actual AI evaluation is Milestone 8.

Builds on Milestones 5–6 (`.graider.yml`, `RepoConfig`, state file).

**Definition of done:**

- `graider review --criteria-dir DIR --dry-run` parses the criteria doc into
  ordered items and prints them, split into "in scope" and "not yet evaluated".
- `--up-to N` (position) or `--up-to <id>` limits the in-scope items; with no
  flag, a `released_up_to` value in the criteria repo's `graider-criteria.yml`
  is used; with neither, all items are in scope.
- Criteria can be loaded from a local dir (`--criteria-dir`) or from the repo's
  own `.graider.yml` (student mode); a GitLab-repo fetch helper exists for
  `--criteria-repo`/`--criteria-path`.
- `ruff`, `ruff format --check`, `ty`, and `pytest` all pass. Parsing is unit
  tested offline (no network).

---

## Step 1 — Dependencies

None new (`pyyaml` is already present from Milestone 6).

---

## Step 2 — File layout

```
src/graider/
├── models.py       # + CriteriaItem, Criteria
├── criteria.py     # NEW: parse + load + staggered cutoff (+ git fetch helper)
├── console.py      # + print_criteria_scope()
└── cli.py          # review: criteria loading + --dry-run preview
tests/
├── test_criteria.py    # NEW (parsing + cutoff, offline)
└── test_cli.py         # + review --dry-run test
```

---

## Step 3 — `models.py`: criteria models

```python
class CriteriaItem(BaseModel):
    id: str        # stable, e.g. "3" or "testing"
    title: str
    body: str = ""
    order: int     # 1-based position


class Criteria(BaseModel):
    brief: str = ""
    items: list[CriteriaItem] = []
```

---

## Step 4 — `src/graider/criteria.py` (NEW)

### Criteria document format

One Markdown or AsciiDoc file. Text before the first item heading is the
**brief**. Each level-2 heading is an **item**, in order:

```markdown
# Project Brief
Build a small library management system...

## 1. Version control
Meaningful commits, feature branches.

## 2. Testing
Unit tests with good coverage.
```

- Markdown item heading marker: `## `. AsciiDoc: `== `.
- Item `id`: the leading `N.` number if present (id `"1"`), else a slug of the
  title (lowercased, spaces→`-`).
- `title`: heading text minus any leading `N.`.
- `body`: text until the next item heading.

### Staggered cutoff

`graider-criteria.yml` (next to the doc) may contain `released_up_to: 2` (a
position) or `released_up_to: testing` (an item id). Precedence for the cutoff:
`--up-to` flag → `released_up_to` → all items.

### Code

```python
"""Load grading criteria (Markdown/AsciiDoc) with ordered items + staggered cutoff."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import yaml

from graider.errors import GraiderError
from graider.models import Criteria, CriteriaItem

_MARKERS = {".md": "## ", ".markdown": "## ", ".adoc": "== ", ".asciidoc": "== "}
_NUM_PREFIX = re.compile(r"^\s*(\d+)[.)]\s*")


def parse_criteria(text: str, marker: str = "## ") -> Criteria:
    lines = text.splitlines()
    brief_lines: list[str] = []
    items: list[CriteriaItem] = []
    current: CriteriaItem | None = None
    body: list[str] = []

    def _flush() -> None:
        if current is not None:
            current.body = "\n".join(body).strip()
            items.append(current)

    for line in lines:
        if line.startswith(marker):
            _flush()
            body = []
            heading = line[len(marker):].strip()
            match = _NUM_PREFIX.match(heading)
            if match:
                item_id = match.group(1)
                title = heading[match.end():].strip()
            else:
                title = heading
                item_id = _slug(title)
            current = CriteriaItem(id=item_id, title=title, order=len(items) + 1)
        elif current is None:
            brief_lines.append(line)
        else:
            body.append(line)
    _flush()

    brief = "\n".join(brief_lines).strip()
    brief = re.sub(r"^#+\s*", "", brief)  # drop a leading markdown/adoc title line marker
    return Criteria(brief=brief, items=items)


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def load_criteria_dir(criteria_dir: Path) -> Criteria:
    """Parse the single criteria document found in a directory."""
    docs = [
        p for p in sorted(criteria_dir.iterdir())
        if p.suffix.lower() in _MARKERS and p.is_file()
    ]
    if not docs:
        raise GraiderError(f"No criteria document (.md/.adoc) found in {criteria_dir}")
    doc = docs[0]
    return parse_criteria(doc.read_text(encoding="utf-8"), _MARKERS[doc.suffix.lower()])


def released_cutoff(criteria_dir: Path) -> str | int | None:
    """Read `released_up_to` from graider-criteria.yml, if present."""
    path = criteria_dir / "graider-criteria.yml"
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("released_up_to")


def split_by_cutoff(
    items: list[CriteriaItem], cutoff: str | int | None
) -> tuple[list[CriteriaItem], list[CriteriaItem]]:
    """Return (in_scope, out_of_scope). cutoff is a 1-based position or an item id."""
    if cutoff is None or cutoff == "":
        return list(items), []
    index = _cutoff_index(items, cutoff)
    return items[:index], items[index:]


def _cutoff_index(items: list[CriteriaItem], cutoff: str | int) -> int:
    text = str(cutoff)
    if text.isdigit():
        return min(int(text), len(items))
    for i, item in enumerate(items):
        if item.id == text:
            return i + 1
    raise GraiderError(f"--up-to {cutoff!r} matches no criteria item id")


def fetch_criteria_repo(repo_url: str, path: str = "", ref: str = "main") -> Path:
    """Shallow-clone a criteria repo and return the local path to `path` inside it.

    Best-effort: relies on git + whatever auth the environment already has for
    repo_url. Tests use local dirs instead.
    """
    tmp = Path(tempfile.mkdtemp(prefix="graider-criteria-"))
    proc = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", ref, repo_url, str(tmp)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise GraiderError(f"Could not clone criteria repo {repo_url}: {proc.stderr.strip()}")
    return tmp / path if path else tmp
```

---

## Step 5 — `console.py`: `print_criteria_scope`

```python
from graider.models import Criteria, CriteriaItem  # extend existing import


def print_criteria_scope(
    in_scope: list[CriteriaItem], out_scope: list[CriteriaItem]
) -> None:
    table = Table(title="Criteria")
    table.add_column("#", justify="right")
    table.add_column("ID")
    table.add_column("Title")
    table.add_column("Scope")
    for item in in_scope:
        table.add_row(str(item.order), item.id, item.title, "[green]in scope[/]")
    for item in out_scope:
        table.add_row(str(item.order), item.id, item.title, "[dim]not yet evaluated[/]")
    console.print(table)
```

---

## Step 6 — `cli.py`: `review` (criteria loading + preview)

```python
from graider.criteria import (
    fetch_criteria_repo, load_criteria_dir, released_cutoff, split_by_cutoff,
)
from graider.console import ..., print_criteria_scope
```

```python
@app.command()
def review(
    ctx: typer.Context,
    repo: Path = typer.Option(Path("."), "--repo"),
    criteria_dir: Optional[Path] = typer.Option(None, "--criteria-dir"),
    criteria_repo: str = typer.Option("", "--criteria-repo"),
    criteria_path: str = typer.Option("", "--criteria-path"),
    up_to: Optional[str] = typer.Option(None, "--up-to", help="Position or item id."),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Evaluate a repo against the (staggered) criteria. (loading + preview)"""
    config = _config(ctx)
    source = _resolve_criteria_dir(repo, criteria_dir, criteria_repo, criteria_path)
    criteria = load_criteria_dir(source)

    cutoff: str | int | None = up_to if up_to is not None else released_cutoff(source)
    in_scope, out_scope = split_by_cutoff(criteria.items, cutoff)

    if dry_run or (dry_run := dry_run or config.dry_run):
        print_criteria_scope(in_scope, out_scope)
        print_success(
            f"{len(in_scope)} of {len(criteria.items)} criteria in scope (dry run)."
        )
        return

    console.print("review: AI evaluation not yet implemented (Milestone 8)")


def _resolve_criteria_dir(repo, criteria_dir, criteria_repo, criteria_path) -> Path:
    if criteria_dir is not None:
        return criteria_dir
    if criteria_repo:
        return fetch_criteria_repo(criteria_repo, criteria_path)
    cfg = load_repo_config(repo)  # student mode: .graider.yml
    if cfg is not None and cfg.criteria_repo:
        return fetch_criteria_repo(cfg.criteria_repo, cfg.criteria_path)
    raise GraiderError(
        "No criteria source: pass --criteria-dir, --criteria-repo, or run in a "
        "repo whose .graider.yml points at a criteria repo."
    )
```

> Keep `load_repo_config` imported (from Milestone 6). Simplify the `dry_run`
> line if you prefer: the intent is "preview when --dry-run or global --dry-run".

---

## Step 7 — Tests

### `tests/test_criteria.py`

```python
import pytest

from graider.criteria import (
    load_criteria_dir, parse_criteria, released_cutoff, split_by_cutoff,
)
from graider.errors import GraiderError

DOC = """# Project Brief
Build a thing.

## 1. Version control
Commit often.

## 2. Testing
Write tests.

## 3. Docs
Explain it.
"""


def test_parse_items_in_order():
    c = parse_criteria(DOC)
    assert [i.id for i in c.items] == ["1", "2", "3"]
    assert [i.title for i in c.items] == ["Version control", "Testing", "Docs"]
    assert c.items[0].order == 1
    assert "Build a thing." in c.brief


def test_parse_slug_id_when_unnumbered():
    c = parse_criteria("## Version Control\nx\n")
    assert c.items[0].id == "version-control"


def test_split_by_position():
    c = parse_criteria(DOC)
    ins, out = split_by_cutoff(c.items, 2)
    assert [i.id for i in ins] == ["1", "2"]
    assert [i.id for i in out] == ["3"]


def test_split_by_id():
    c = parse_criteria(DOC)
    ins, out = split_by_cutoff(c.items, "2")
    assert len(ins) == 2 and len(out) == 1


def test_split_none_is_all():
    c = parse_criteria(DOC)
    ins, out = split_by_cutoff(c.items, None)
    assert len(ins) == 3 and out == []


def test_unknown_cutoff_raises():
    c = parse_criteria(DOC)
    with pytest.raises(GraiderError):
        split_by_cutoff(c.items, "nope")


def test_load_dir_and_released(tmp_path):
    (tmp_path / "criteria.md").write_text(DOC)
    (tmp_path / "graider-criteria.yml").write_text("released_up_to: 1\n")
    c = load_criteria_dir(tmp_path)
    assert len(c.items) == 3
    assert released_cutoff(tmp_path) == 1
```

### `tests/test_cli.py` — review preview

```python
def test_review_dry_run_lists_scope(tmp_path, monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    (tmp_path / "criteria.md").write_text("# Brief\nx\n\n## 1. A\na\n\n## 2. B\nb\n")
    result = run_cli(
        [*_no_config(tmp_path), "review",
         "--criteria-dir", str(tmp_path), "--up-to", "1", "--dry-run"]
    )
    assert result.exit_code == 0
    assert "in scope" in result.output
    assert "not yet evaluated" in result.output
```

---

## Step 8 — Verify

```sh
uv sync
uv run ruff check . && uv run ruff format --check . && uv run ty check
uv run pytest -q

mkdir -p /tmp/crit && printf '# Brief\nDo the thing.\n\n## 1. VCS\na\n\n## 2. Tests\nb\n\n## 3. Docs\nc\n' > /tmp/crit/criteria.md
uv run graider review --criteria-dir /tmp/crit --up-to 2 --dry-run
```

---

## Notes for the next milestone

- **Milestone 8** consumes `in_scope` items + the `grade-results.json` from
  Milestone 6 + the repo contents as the AI review inputs, and truncates the
  criteria at exactly this cutoff.
- `fetch_criteria_repo` is best-effort (git + ambient auth). If criteria repos
  are private and CI needs them, pass a tokenized URL or reuse `GitLabClient`.
```
