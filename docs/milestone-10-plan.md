# Milestone 10 — Detailed Implementation Plan

**Goal:** `graider report` merges the grade metrics (`grade-results.json`) and AI
review (`review-results.json`) into a **per-group Markdown report** plus one
**instructor CSV** summary.

Builds on Milestone 6 (`GradeResult` / `grade-results.json`), Milestone 8
(`ReviewResult` / `review-results.json`), and Milestone 5 (`graider.lock.json`
for project URLs).

**Definition of done:**

- `graider report` in a dir with `grade-results.json` and/or
  `review-results.json` writes `reports/<project>.md` and `reports/summary.csv`.
- `graider report --workspace DIR` does the same for every immediate subdir that
  has those files.
- With `--state graider.lock.json`, each report includes the project's GitLab URL.
- Pure logic — no network, no AI. `ruff`, `ruff format --check`, `ty`, `pytest`
  pass. Fully unit tested with JSON fixtures.

---

## Step 1 — Dependencies

None (stdlib `json`, `csv`).

---

## Step 2 — File layout

```
src/graider/
├── report/
│   ├── __init__.py
│   └── build.py        # NEW: load results, render markdown, write CSV
├── console.py          # + print_report_summary()
└── cli.py              # report: real implementation
tests/
└── test_report.py      # NEW (fixtures, no network)
```

---

## Step 3 — `src/graider/report/build.py` (NEW)

### Behavior

- `load_grades(path)` → `list[GradeResult]` (Milestone 6 writes a JSON list).
- `load_reviews(path)` → `list[ReviewResult]` (Milestone 8 writes a single
  object; accept an object **or** a list).
- `render_report(grade, review, url)` → Markdown string for one project (either
  input may be `None`).
- `summary_row(grade, review, url)` → dict for the CSV.
- `project_urls(state_path)` → `{project_name: web_url}` from the state file
  (empty if no state).

### Code

```python
"""Merge grade + review results into per-project Markdown and a summary CSV."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from graider.errors import GraiderError
from graider.models import GradeResult, ReviewResult, SetupState

CSV_COLUMNS = [
    "project", "url", "template", "tests_passed", "tests_failed",
    "coverage_percent", "qlty_issues", "qlty_smells",
    "criteria_met", "criteria_total", "review_model",
]


def load_grades(path: Path) -> list[GradeResult]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else [data]
    return [GradeResult.model_validate(r) for r in rows]


def load_reviews(path: Path) -> list[ReviewResult]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else [data]
    return [ReviewResult.model_validate(r) for r in rows]


def project_urls(state_path: Path | None) -> dict[str, str]:
    if state_path is None or not state_path.exists():
        return {}
    try:
        state = SetupState.model_validate_json(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GraiderError(f"Could not read state file {state_path}: {exc}") from exc
    return {p.name: p.web_url for p in state.projects.values()}


def render_report(
    grade: GradeResult | None, review: ReviewResult | None, url: str = ""
) -> str:
    name = (grade.project if grade else None) or (review.project if review else "project")
    lines = [f"# {name}", ""]
    if url:
        lines += [f"Project: {url}", ""]

    if grade is not None:
        cov = "-" if grade.coverage_percent is None else f"{grade.coverage_percent}%"
        lines += [
            "## Metrics",
            "",
            f"- Template: {grade.template}",
            f"- Tests: {grade.tests_passed} passed / {grade.tests_failed} failed",
            f"- Coverage: {cov}",
            f"- qlty: {grade.qlty_issues} issues, {grade.qlty_smells} smells",
        ]
        if grade.errors:
            lines.append(f"- Tool notes: {'; '.join(grade.errors)}")
        lines.append("")

    if review is not None:
        met = sum(v.met for v in review.criteria)
        lines += [
            f"## Review (model {review.model}, cutoff {review.cutoff or 'all'})",
            "",
            f"**{met}/{len(review.criteria)} criteria met.** {review.overall_summary}",
            "",
            "| ID | Criterion | Met | Comment |",
            "| --- | --- | --- | --- |",
        ]
        for v in review.criteria:
            mark = "✓" if v.met else "✗"
            lines.append(f"| {v.id} | {v.title} | {mark} | {v.comment} |")
        lines.append("")
        evidence = [e for v in review.criteria for e in v.evidence]
        if evidence:
            lines += ["### Evidence", ""] + [f"- {e}" for e in evidence] + [""]

    return "\n".join(lines)


def summary_row(
    grade: GradeResult | None, review: ReviewResult | None, url: str = ""
) -> dict[str, object]:
    name = (grade.project if grade else None) or (review.project if review else "project")
    return {
        "project": name,
        "url": url,
        "template": grade.template if grade else "",
        "tests_passed": grade.tests_passed if grade else "",
        "tests_failed": grade.tests_failed if grade else "",
        "coverage_percent": grade.coverage_percent if grade else "",
        "qlty_issues": grade.qlty_issues if grade else "",
        "qlty_smells": grade.qlty_smells if grade else "",
        "criteria_met": sum(v.met for v in review.criteria) if review else "",
        "criteria_total": len(review.criteria) if review else "",
        "review_model": review.model if review else "",
    }


def write_csv(rows: list[dict[str, object]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
```

---

## Step 4 — `console.py`: `print_report_summary`

```python
def print_report_summary(rows: list[dict[str, object]], out_dir: Path) -> None:
    table = Table(title="Report")
    table.add_column("Project", style="bold")
    table.add_column("Tests", justify="right")
    table.add_column("Cov %", justify="right")
    table.add_column("Criteria", justify="right")
    for row in rows:
        tests = f"{row['tests_passed']}/{row['tests_failed']}" if row["tests_passed"] != "" else "-"
        cov = row["coverage_percent"] if row["coverage_percent"] != "" else "-"
        crit = (
            f"{row['criteria_met']}/{row['criteria_total']}"
            if row["criteria_total"] != "" else "-"
        )
        table.add_row(str(row["project"]), str(tests), str(cov), str(crit))
    console.print(table)
```

---

## Step 5 — `cli.py`: implement `report`

Replace the `report` stub with:

```python
from graider.report.build import (
    load_grades, load_reviews, project_urls, render_report, summary_row, write_csv,
)
from graider.console import ..., print_report_summary
```

```python
@app.command()
def report(
    ctx: typer.Context,
    workspace: Optional[Path] = typer.Option(None, "--workspace"),
    grade_file: Path = typer.Option(Path("grade-results.json"), "--grade"),
    review_file: Path = typer.Option(Path("review-results.json"), "--review"),
    state: Optional[Path] = typer.Option(None, "--state"),
    out_dir: Path = typer.Option(Path("reports"), "--out-dir"),
) -> None:
    """Merge grade + review results into per-project reports and a CSV."""
    urls = project_urls(state)
    out_dir.mkdir(parents=True, exist_ok=True)

    dirs = (
        sorted(d for d in workspace.iterdir() if d.is_dir())
        if workspace is not None
        else [Path(".")]
    )

    rows: list[dict[str, object]] = []
    for d in dirs:
        grades = load_grades(d / grade_file.name)
        reviews = {r.project: r for r in load_reviews(d / review_file.name)}
        # index grades by project; pair with a review of the same project name
        by_project = {g.project: g for g in grades}
        names = list(by_project) or list(reviews)
        if not names:
            continue
        for name in names:
            grade = by_project.get(name)
            review = reviews.get(name)
            url = urls.get(name, "")
            (out_dir / f"{name}.md").write_text(render_report(grade, review, url), encoding="utf-8")
            rows.append(summary_row(grade, review, url))

    if not rows:
        raise GraiderError("No grade-results.json / review-results.json found to report on.")

    write_csv(rows, out_dir / "summary.csv")
    print_report_summary(rows, out_dir)
    print_success(f"Wrote {len(rows)} report(s) → {out_dir}")
```

> The single-dir case (`--workspace` omitted) reads the files in the current
> directory. `grade_file.name` / `review_file.name` are used so `--workspace`
> looks for the same filenames inside each subdir.

---

## Step 6 — Tests (`tests/test_report.py`)

```python
import csv
import json
from pathlib import Path

from graider.models import CriterionVerdict, GradeResult, ReviewResult
from graider.report.build import (
    load_grades, load_reviews, render_report, summary_row, write_csv,
)


def _grade():
    return GradeResult(
        project="brave-otter", template="python", qlty_issues=1, qlty_smells=2,
        tests_passed=3, tests_failed=0, coverage_percent=88.0,
    )


def _review():
    return ReviewResult(
        project="brave-otter", head_sha="abc", model="claude-opus-4-8", cutoff="2",
        overall_summary="Good work.",
        criteria=[
            CriterionVerdict(id="1", title="VCS", met=True, evidence=["a.py:1 — ok"], comment="clean"),
            CriterionVerdict(id="2", title="Tests", met=False, evidence=[], comment="add more"),
        ],
    )


def test_render_includes_both(tmp_path):
    md = render_report(_grade(), _review(), url="https://gl/x")
    assert "# brave-otter" in md
    assert "88.0%" in md
    assert "1/2 criteria met" in md
    assert "https://gl/x" in md
    assert "a.py:1 — ok" in md


def test_render_grade_only():
    md = render_report(_grade(), None)
    assert "## Metrics" in md
    assert "## Review" not in md


def test_summary_row():
    row = summary_row(_grade(), _review(), url="u")
    assert row["criteria_met"] == 1 and row["criteria_total"] == 2
    assert row["coverage_percent"] == 88.0


def test_load_grades_list(tmp_path):
    p = tmp_path / "grade-results.json"
    p.write_text(json.dumps([_grade().model_dump()]))
    assert load_grades(p)[0].project == "brave-otter"


def test_load_reviews_single_object(tmp_path):
    p = tmp_path / "review-results.json"
    p.write_text(_review().model_dump_json())
    assert load_reviews(p)[0].project == "brave-otter"


def test_write_csv(tmp_path):
    out = tmp_path / "summary.csv"
    write_csv([summary_row(_grade(), _review())], out)
    rows = list(csv.DictReader(out.open()))
    assert rows[0]["project"] == "brave-otter"
    assert rows[0]["criteria_met"] == "1"
```

Add one CLI test in `tests/test_cli.py` for the single-dir happy path (write both
JSON files in `tmp_path`, run `report --out-dir ...`, assert exit 0 + a `.md` and
`summary.csv` exist).

---

## Step 7 — Verify

```sh
uv sync
uv run ruff check . && uv run ruff format --check . && uv run ty check
uv run pytest -q

# manual, offline end-to-end from a rendered starter:
uv run graider template render --template python --out /tmp/proj >/dev/null
(cd /tmp/proj && git init -q && git add -A && git commit -qm x \
   && UV_CACHE_DIR=/tmp/uvc uv run --project /home/sandro/work/grAIder graider grade --repo . )
# (review needs credentials; report will include just metrics if review json is absent)
(cd /tmp/proj && uv run --project /home/sandro/work/grAIder graider report --out-dir reports && ls reports)
```

---

## Notes

- This closes the core pipeline (setup → grade → review → report). The
  `--workspace` layout (one subdir per cloned project, each with its result
  JSON) is what a teacher gets after `grade --workspace` + per-repo `review`.
- Reports are Markdown so they render on GitLab; the CSV is the gradebook import.
- Extensions **E1–E6** (`feature-requests-plan.md`) build on the finished
  pipeline next.
```
