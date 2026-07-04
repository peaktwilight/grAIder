# Milestone 6 — Detailed Implementation Plan

**Goal:** `graider grade` — run qlty (issues + smells) and the project's tests
(+ coverage) over one repo (student self-assessment) or a workspace of repos
(teacher), normalize into a `GradeResult` per project, and emit a metrics table
plus a `grade-results.json`.

This document is prescriptive. Build on Milestones 4–5 (`.graider.yml` shape,
`TemplateName`, state file).

**Definition of done:**

- `graider grade` in a repo containing `.graider.yml` grades that repo.
- `graider grade --workspace DIR` grades every immediate subdirectory that
  contains a `.graider.yml`.
- Each `GradeResult` has qlty issue/smell counts, test pass/fail counts, and a
  coverage percent (python; best-effort/None for java/cpp), plus an `errors`
  list for any tool that could not run.
- Results print as a Rich table and are written to `--results` (default
  `grade-results.json`).
- Missing tools (e.g. `qlty` not installed) degrade gracefully into `errors`,
  never a crash.
- `ruff`, `ruff format --check`, `ty`, and `pytest` (unit) pass.

---

## Step 1 — Dependency

`.graider.yml` must now be *read*, so add pyyaml:

```toml
dependencies = [ ..., "pyyaml>=6.0" ]
```

`uv sync`. (Coverage tools stay out of grAIder's deps — python coverage is
pulled ephemerally with `uv run --with pytest-cov`; java/cpp coverage is
best-effort.)

---

## Step 2 — File layout

```
src/graider/
├── models.py            # + GradeResult
├── project_config.py    # NEW: read .graider.yml
├── grading/
│   ├── __init__.py
│   └── runner.py        # NEW: grade_project() + qlty/test/coverage parsing
├── console.py           # + print_grade_table()
└── cli.py               # grade: real implementation
tests/
├── test_project_config.py   # NEW
├── test_grading.py          # NEW (parser unit tests with fixtures)
└── integration/test_grade.py  # NEW (marker-gated, real python grade)
```

---

## Step 3 — `models.py`: `GradeResult`

```python
class GradeResult(BaseModel):
    project: str
    template: str
    qlty_issues: int = 0
    qlty_smells: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    coverage_percent: float | None = None
    errors: list[str] = []
```

---

## Step 4 — `src/graider/project_config.py` (NEW)

```python
"""Read a student repo's .graider.yml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from graider.errors import GraiderError


class RepoConfig(BaseModel):
    course: str = ""
    template: str
    criteria_repo: str = ""
    criteria_path: str = ""


def load_repo_config(repo_dir: Path) -> RepoConfig | None:
    """Return the repo's .graider.yml as a RepoConfig, or None if absent."""
    path = repo_dir / ".graider.yml"
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise GraiderError(f"Invalid .graider.yml in {repo_dir}: {exc}") from exc
    criteria = data.get("criteria") or {}
    template = data.get("template")
    if not template:
        raise GraiderError(f".graider.yml in {repo_dir} is missing `template`")
    return RepoConfig(
        course=data.get("course", ""),
        template=template,
        criteria_repo=criteria.get("repo", ""),
        criteria_path=criteria.get("path", ""),
    )
```

---

## Step 5 — `src/graider/grading/runner.py` (NEW)

Design rules:
- Every external command is wrapped so a missing tool or nonzero exit becomes an
  `errors` entry, never an exception.
- Test pass/fail comes from a **JUnit XML** file (uniform across languages).
- Coverage: python via `uv run --with pytest-cov` (no change to the student
  repo); java/cpp left as `None` (best-effort — note for a later pass).

```python
"""Run qlty + tests over a repo and normalize into a GradeResult."""

from __future__ import annotations

import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from graider.errors import GraiderError
from graider.models import GradeResult
from graider.project_config import load_repo_config


def grade_project(repo_dir: Path) -> GradeResult:
    config = load_repo_config(repo_dir)
    if config is None:
        raise GraiderError(f"No .graider.yml found in {repo_dir}")
    result = GradeResult(project=repo_dir.name, template=config.template)
    _run_qlty(repo_dir, result)
    _run_tests(repo_dir, config.template, result)
    return result


def _capture(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def _run_qlty(repo_dir: Path, result: GradeResult) -> None:
    if not shutil.which("qlty"):
        result.errors.append("qlty not installed; skipped issues/smells")
        return
    check = _capture(["qlty", "check", "--no-fail", "--format=json"], repo_dir)
    result.qlty_issues = _count_json_array(check.stdout)
    smells = _capture(["qlty", "smells", "--format=json"], repo_dir)
    result.qlty_smells = _count_json_array(smells.stdout)


def _count_json_array(text: str) -> int:
    try:
        data = json.loads(text or "[]")
    except json.JSONDecodeError:
        return 0
    return len(data) if isinstance(data, list) else 0


def _run_tests(repo_dir: Path, template: str, result: GradeResult) -> None:
    handlers = {"python": _tests_python, "java": _tests_java, "cpp": _tests_cpp}
    handler = handlers.get(template)
    if handler is None:
        result.errors.append(f"no test runner for template {template!r}")
        return
    handler(repo_dir, result)


def _tests_python(repo_dir: Path, result: GradeResult) -> None:
    junit = repo_dir / ".graider-junit.xml"
    cov = repo_dir / ".graider-cov.json"
    _capture(
        [
            "uv", "run", "--with", "pytest-cov", "pytest",
            f"--junit-xml={junit}", "--cov=.", f"--cov-report=json:{cov}",
        ],
        repo_dir,
    )
    _parse_junit(junit, result)
    _parse_coverage_json(cov, result)


def _tests_java(repo_dir: Path, result: GradeResult) -> None:
    _capture(["gradle", "test", "--no-daemon"], repo_dir)
    # gradle writes one XML per test class under build/test-results/test/
    reports = sorted((repo_dir / "build" / "test-results" / "test").glob("*.xml"))
    _parse_junit_many(reports, result)


def _tests_cpp(repo_dir: Path, result: GradeResult) -> None:
    junit = repo_dir / ".graider-junit.xml"
    _capture(["cmake", "-B", "build"], repo_dir)
    _capture(["cmake", "--build", "build"], repo_dir)
    _capture(
        ["ctest", "--test-dir", "build", f"--output-junit={junit}"], repo_dir
    )
    _parse_junit(junit, result)


def _parse_junit(path: Path, result: GradeResult) -> None:
    if not path.exists():
        result.errors.append("no test results produced")
        return
    _parse_junit_many([path], result)


def _parse_junit_many(paths: list[Path], result: GradeResult) -> None:
    if not paths:
        result.errors.append("no test results produced")
        return
    total = failed = 0
    for path in paths:
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
        for suite in suites:
            total += int(suite.get("tests", "0"))
            failed += int(suite.get("failures", "0")) + int(suite.get("errors", "0"))
    result.tests_passed = total - failed
    result.tests_failed = failed


def _parse_coverage_json(path: Path, result: GradeResult) -> None:
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        result.coverage_percent = round(data["totals"]["percent_covered"], 1)
    except (json.JSONDecodeError, KeyError, OSError):
        pass
```

> `qlty check`/`smells` JSON shape is best-effort (as in Milestone 4): we count
> top-level array entries. Verify against real `qlty --format=json` output and
> adjust `_count_json_array` if qlty nests results under a key.

---

## Step 6 — `console.py`: `print_grade_table`

```python
from graider.models import GradeResult  # extend existing models import


def print_grade_table(results: list[GradeResult]) -> None:
    table = Table(title="Grades")
    table.add_column("Project", style="bold")
    table.add_column("Tmpl")
    table.add_column("Tests", justify="right")
    table.add_column("Cov %", justify="right")
    table.add_column("Issues", justify="right")
    table.add_column("Smells", justify="right")
    table.add_column("Notes")
    for r in results:
        tests = f"[green]{r.tests_passed}[/]" if r.tests_failed == 0 else (
            f"[red]{r.tests_passed}/{r.tests_passed + r.tests_failed}[/]"
        )
        cov = "-" if r.coverage_percent is None else f"{r.coverage_percent}"
        table.add_row(
            r.project, r.template, tests, cov,
            str(r.qlty_issues), str(r.qlty_smells), "; ".join(r.errors),
        )
    console.print(table)
```

---

## Step 7 — `cli.py`: implement `grade`

```python
from graider.grading.runner import grade_project
from graider.project_config import load_repo_config
from graider.console import ..., print_grade_table
```

```python
@app.command()
def grade(
    ctx: typer.Context,
    repo: Path = typer.Option(Path("."), "--repo", help="Repo to grade (student mode)."),
    workspace: Path = typer.Option(
        None, "--workspace", help="Grade every subdir with a .graider.yml (teacher mode).",
    ),
    results: Path = typer.Option(Path("grade-results.json"), "--results"),
) -> None:
    """Grade a repo (or a workspace of repos) with qlty + tests + coverage."""
    if workspace is not None:
        targets = sorted(
            d for d in workspace.iterdir() if (d / ".graider.yml").exists()
        )
        if not targets:
            raise GraiderError(f"No repos with a .graider.yml under {workspace}")
    else:
        if load_repo_config(repo) is None:
            raise GraiderError(f"No .graider.yml in {repo}; pass --workspace for teacher mode.")
        targets = [repo]

    graded = [grade_project(t) for t in targets]
    print_grade_table(graded)
    results.write_text(
        json.dumps([g.model_dump() for g in graded], indent=2) + "\n", encoding="utf-8"
    )
    print_success(f"Graded {len(graded)} project(s) → {results}")
```

Add `import json` and `from graider.errors import GraiderError` if not present.

---

## Step 8 — Tests

### `tests/test_project_config.py`

- Writing a `.graider.yml` and loading it returns the right `template`/criteria.
- Missing file → `None`.
- Missing `template` key → `GraiderError`.

### `tests/test_grading.py` (parser unit tests — fast, no toolchain)

- `_parse_junit_many` on a fixture XML string
  (`<testsuite tests="3" failures="1" errors="0">`) → passed 2, failed 1.
- Multiple suites summed.
- `_parse_coverage_json` on `{"totals": {"percent_covered": 87.5}}` → 87.5.
- `_run_qlty` with qlty absent (monkeypatch `shutil.which` → None) appends an
  error and leaves counts at 0.
- `_count_json_array` on `"[]"`, a 2-element array, and garbage.

Write these by calling the `_`-helpers directly with a `GradeResult()` instance.

### `tests/integration/test_grade.py` (marker `integration`, python only)

```python
import pytest
from graider.grading.runner import grade_project
from graider.templates import TemplateContext, render_template, write_files

pytestmark = pytest.mark.integration


@pytest.mark.skipif(not __import__("shutil").which("uv"), reason="uv missing")
def test_grade_python_starter(tmp_path):
    repo = tmp_path / "proj"
    write_files(render_template("python", TemplateContext()), repo)
    result = grade_project(repo)
    assert result.tests_passed >= 1
    assert result.tests_failed == 0
```

Remember the inner-uv cache isolation lesson from the starter integration test:
if this test runs `uv` as a subprocess under CI's relative `UV_CACHE_DIR`, set an
absolute `UV_CACHE_DIR` outside `repo` in the subprocess env (do it inside
`_tests_python` via an explicit `env`, or the CI job will lint/collect the cache).

---

## Step 9 — Verify

```sh
uv sync
uv run ruff check . && uv run ruff format --check . && uv run ty check
uv run pytest -q
uv run pytest -m integration -k grade   # runs the python grade end-to-end

# manual: render a starter, grade it
uv run graider template render --template python --out /tmp/g && \
  (cd /tmp/g && uv run graider grade)
```

---

## Notes for the next milestones

- **Milestone 7** loads the criteria repo (ordered items + staggered cutoff);
  `grade-results.json` from here becomes an input to **Milestone 8**'s AI review.
- Teacher-mode cloning from `graider.lock.json` is intentionally out of scope
  here (grade operates on local dirs). If you add it, clone each project's
  `web_url` into the workspace with an authenticated URL, then reuse
  `grade_project`.
- Java/cpp coverage is `None` for now; wire jacoco / gcovr when the starters
  gain those plugins.
```
