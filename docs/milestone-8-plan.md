# Milestone 8 — Detailed Implementation Plan

**Goal:** `graider review` (non-dry-run) evaluates a repo against the in-scope
criteria using Claude, producing a **structured, auditable verdict** (per-criterion
met/not-met + evidence + overall summary), printed as a table and written to
`review-results.json`.

Builds on Milestone 7 (criteria loading + `--up-to`/`released_up_to` cutoff) and
Milestone 6 (`grade-results.json`).

## Design decision: single structured call, not an agent

Per Anthropic's own guidance ("default to the simplest tier; only reach for
agents when the task needs open-ended exploration"), this uses the **`anthropic`
SDK Messages API with structured outputs** (`client.messages.parse()` + a Pydantic
schema) — one call per project — rather than the Claude Agent SDK. Repo files are
collected and passed as context. If deeper repo exploration is later needed,
upgrade this one module to a tool-use loop; nothing else changes.

**Model:** default `claude-opus-4-8` (overridable via `--model`).

**Definition of done:**

- `graider review --criteria-dir DIR` (no `--dry-run`) runs the model over the
  repo, prints a per-criterion verdict table, and writes `review-results.json`.
- Only in-scope criteria (from the Milestone 7 cutoff) are sent to the model.
- Re-running skips the model call when the repo HEAD SHA is unchanged (unless
  `--force`).
- Missing/invalid API credentials produce a clean `GraiderError`, not a traceback.
- `ruff`, `ruff format --check`, `ty`, and `pytest` pass. **Unit tests mock the
  Anthropic client — no network, no API key needed in CI.**

---

## Step 1 — Dependency

```sh
uv add anthropic     # latest; provides messages.parse + structured outputs
```

Credentials resolve the standard way: `ANTHROPIC_API_KEY`, or an `ant auth login`
profile. Do **not** require the env var explicitly — let the SDK resolve it and
wrap failures (below).

---

## Step 2 — File layout

```
src/graider/
├── models.py            # + CriterionVerdict, ReviewOutput, ReviewResult
├── review/
│   ├── __init__.py
│   └── agent.py         # NEW: collect files, build prompt, call model
├── console.py           # + print_review()
└── cli.py               # review: real (non-dry-run) path
tests/
└── test_review.py       # NEW (mocked client, no network)
```

---

## Step 3 — `models.py`: review schemas

```python
class CriterionVerdict(BaseModel):
    id: str
    title: str
    met: bool
    evidence: list[str]   # e.g. "src/calc.py:12 — no error handling"
    comment: str


class ReviewOutput(BaseModel):
    """Exactly what the model returns (structured-output schema)."""

    overall_summary: str
    criteria: list[CriterionVerdict]


class ReviewResult(BaseModel):
    """Persisted result = model output + run metadata."""

    project: str
    head_sha: str
    model: str
    cutoff: str
    overall_summary: str
    criteria: list[CriterionVerdict]
```

> Keep `ReviewOutput` fields **required** (no defaults) so the structured-output
> schema forces the model to fill them.

---

## Step 4 — `src/graider/review/agent.py` (NEW)

### Behavior

- Collect a bounded set of repo source files (skip `.git`, `build`, `.venv`,
  `node_modules`, binary/large files; cap total bytes so token usage stays
  sane).
- Build one prompt: the project brief, the **in-scope** criteria items, the
  grade metrics (if a `GradeResult` is passed), and the collected file contents.
- Call `client.messages.parse(..., output_format=ReviewOutput)`; wrap **any**
  SDK failure in a `GraiderError` that names the credential fix.
- Attach metadata (project, head SHA, model, cutoff) → `ReviewResult`.

### Code

```python
"""Agentic (single structured call) review of a repo against criteria."""

from __future__ import annotations

import subprocess
from pathlib import Path

import anthropic

from graider.errors import GraiderError
from graider.models import CriteriaItem, GradeResult, ReviewOutput, ReviewResult

DEFAULT_MODEL = "claude-opus-4-8"
_MAX_TOTAL_BYTES = 200_000
_SKIP_DIRS = {".git", "build", ".venv", "venv", "node_modules", "__pycache__", ".qlty"}
_TEXT_SUFFIXES = {
    ".py", ".java", ".kt", ".kts", ".cpp", ".hpp", ".h", ".c", ".cc",
    ".md", ".txt", ".toml", ".cfg", ".yml", ".yaml", ".cmake", ".gradle",
}

_SYSTEM = (
    "You are a strict but fair programming-course grader. Evaluate the student "
    "repository against each provided criterion. For each criterion decide met "
    "(true/false), cite concrete evidence as 'path:line — note', and keep "
    "comments short and actionable. Judge only the criteria you are given."
)


def review_project(
    repo_dir: Path,
    brief: str,
    in_scope: list[CriteriaItem],
    *,
    grade: GradeResult | None = None,
    cutoff: str = "",
    model: str = DEFAULT_MODEL,
    client: anthropic.Anthropic | None = None,
) -> ReviewResult:
    client = client or anthropic.Anthropic()
    user_prompt = _build_prompt(brief, in_scope, grade, _collect_files(repo_dir))

    try:
        response = client.messages.parse(
            model=model,
            max_tokens=16000,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
            output_format=ReviewOutput,
        )
    except Exception as exc:  # wrap SDK/auth/network errors into a clean message
        raise GraiderError(
            f"AI review failed ({exc}). Check your Anthropic credentials "
            "(set ANTHROPIC_API_KEY or run `ant auth login`)."
        ) from exc

    output = response.parsed_output
    return ReviewResult(
        project=repo_dir.name,
        head_sha=head_sha(repo_dir),
        model=model,
        cutoff=cutoff,
        overall_summary=output.overall_summary,
        criteria=output.criteria,
    )


def head_sha(repo_dir: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
        capture_output=True, text=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _collect_files(repo_dir: Path) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    total = 0
    for path in sorted(repo_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        total += len(text.encode("utf-8"))
        if total > _MAX_TOTAL_BYTES:
            break
        files.append((str(path.relative_to(repo_dir)), text))
    return files


def _build_prompt(
    brief: str,
    in_scope: list[CriteriaItem],
    grade: GradeResult | None,
    files: list[tuple[str, str]],
) -> str:
    parts = [f"# Project brief\n{brief or '(none provided)'}", "\n# Criteria to evaluate"]
    for item in in_scope:
        parts.append(f"\n## {item.id}. {item.title}\n{item.body}")
    if grade is not None:
        parts.append(
            "\n# Automated metrics\n"
            f"tests: {grade.tests_passed} passed / {grade.tests_failed} failed; "
            f"coverage: {grade.coverage_percent}; "
            f"qlty issues: {grade.qlty_issues}; smells: {grade.qlty_smells}"
        )
    parts.append("\n# Repository files")
    for rel, text in files:
        parts.append(f"\n--- {rel} ---\n{text}")
    return "\n".join(parts)
```

> The broad `except Exception` is deliberate and scoped to the single API call —
> a CLI should never dump an SDK traceback for a bad key. Do not widen its scope.

---

## Step 5 — `console.py`: `print_review`

```python
from graider.models import ReviewResult  # extend existing import


def print_review(result: ReviewResult) -> None:
    table = Table(title=f"Review — {result.project}")
    table.add_column("ID")
    table.add_column("Criterion")
    table.add_column("Met")
    table.add_column("Comment")
    for verdict in result.criteria:
        met = "[green]✓[/]" if verdict.met else "[red]✗[/]"
        table.add_row(verdict.id, verdict.title, met, verdict.comment)
    console.print(table)
    console.print(f"\n[bold]Summary:[/] {result.overall_summary}")
```

---

## Step 6 — `cli.py`: the real `review` path

Replace the Milestone-7 stub line
(`console.print("review: AI evaluation not yet implemented (Milestone 8)")`)
with the model call. Add `--model`, `--force`, and `--results` options to the
`review` command signature. After computing `in_scope` (Milestone 7):

```python
import json
from graider.review.agent import DEFAULT_MODEL, head_sha, review_project
from graider.console import ..., print_review
from graider.grading.runner import ...  # not needed; grade is optional here
```

```python
    # ... dry_run branch returns above ...

    results_path = results  # from a new --results option (default Path("review-results.json"))
    if not force and results_path.exists():
        prior = json.loads(results_path.read_text())
        if prior.get("head_sha") and prior["head_sha"] == head_sha(repo):
            console.print("Repo unchanged since last review; use --force to re-run.")
            return

    result = review_project(
        repo, criteria.brief, in_scope,
        cutoff=str(cutoff) if cutoff is not None else "",
        model=model,
    )
    print_review(result)
    results_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print_success(f"Reviewed {len(in_scope)} criteria → {results_path}")
```

New options on `review`:

```python
    model: str = typer.Option(DEFAULT_MODEL, "--model", help="Claude model id."),
    force: bool = typer.Option(False, "--force", help="Re-review even if HEAD is unchanged."),
    results: Path = typer.Option(Path("review-results.json"), "--results"),
```

> Add `review-results.json` to `.gitignore` (a run artifact, like
> `grade-results.json`).

---

## Step 7 — Tests (`tests/test_review.py`, fully mocked)

```python
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from graider.errors import GraiderError
from graider.models import CriteriaItem, CriterionVerdict, ReviewOutput
from graider.review.agent import _build_prompt, _collect_files, review_project


def _items():
    return [
        CriteriaItem(id="1", title="Testing", body="Has tests.", order=1),
        CriteriaItem(id="2", title="Docs", body="Has a README.", order=2),
    ]


def _fake_client(output):
    client = MagicMock()
    client.messages.parse.return_value = MagicMock(parsed_output=output)
    return client


def test_review_maps_output(tmp_path):
    (tmp_path / "main.py").write_text("print('hi')\n")
    output = ReviewOutput(
        overall_summary="Solid.",
        criteria=[CriterionVerdict(id="1", title="Testing", met=True, evidence=[], comment="ok")],
    )
    result = review_project(
        tmp_path, "brief", _items(), client=_fake_client(output), model="m"
    )
    assert result.overall_summary == "Solid."
    assert result.criteria[0].met is True
    assert result.model == "m"
    assert result.project == tmp_path.name


def test_review_wraps_sdk_errors(tmp_path):
    client = MagicMock()
    client.messages.parse.side_effect = RuntimeError("401 unauthorized")
    with pytest.raises(GraiderError, match="Anthropic credentials"):
        review_project(tmp_path, "brief", _items(), client=client)


def test_prompt_only_includes_in_scope():
    prompt = _build_prompt("brief", _items()[:1], None, [("a.py", "x")])
    assert "Testing" in prompt
    assert "Docs" not in prompt


def test_collect_files_skips_junk(tmp_path):
    (tmp_path / "keep.py").write_text("a\n")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "x.py").write_text("junk\n")
    (tmp_path / "img.png").write_bytes(b"\x89PNG")
    names = {rel for rel, _ in _collect_files(tmp_path)}
    assert "keep.py" in names
    assert not any(".venv" in n for n in names)
    assert "img.png" not in names
```

> The `test_review_wraps_sdk_errors` test raises a plain `RuntimeError` on
> purpose — the broad `except Exception` in `review_project` is what turns any
> SDK failure into a clean `GraiderError`, so the test needn't construct a real
> `anthropic.AuthenticationError`.

---

## Step 8 — Verify

```sh
uv sync
uv run ruff check . && uv run ruff format --check . && uv run ty check
uv run pytest -q        # all mocked, no network

# manual (needs real credentials + a repo with .graider.yml or --criteria-dir):
mkdir -p /tmp/crit && printf '# Brief\nx\n\n## 1. Testing\nHas tests.\n' > /tmp/crit/criteria.md
uv run graider template render --template python --out /tmp/proj >/dev/null
uv run graider review --repo /tmp/proj --criteria-dir /tmp/crit --up-to 1
```

---

## Notes for the next milestones

- `ReviewResult` carries `file:line` evidence, `head_sha`, and per-criterion
  verdicts — exactly what the **E3/E4 feedback features** (MR comments / issues,
  from `feature-requests-plan.md`) post back to GitLab.
- **Milestone 9** (teacher authoring) generates the criteria this consumes; the
  ordered-item format is shared.
- **Milestone 10** (reports) merges `grade-results.json` + `review-results.json`
  into per-group reports; keep both JSON schemas stable.
- Cost controls in place: `--model`, a bounded file collection, and SHA-based
  skip. If reviews get expensive, add prompt caching on the criteria/system
  prefix (see the caching guidance) — the system prompt and criteria are the
  stable prefix.
```
