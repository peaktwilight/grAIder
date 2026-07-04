# Milestone 5 — Detailed Implementation Plan

**Goal:** wire `graider setup` end to end — read the roster, resolve the org,
and for each group: pick a random project name, create the project, push the
starter, protect `main`, and invite members — recording everything into a
committed `graider.lock.json` state file so re-runs are idempotent.

This document is prescriptive. Follow the steps in order. Where full code is
given, you may copy it verbatim. It builds directly on Milestones 2–4
(`read_roster`/`group_students`, `GitLabClient`, `render_template`/`commit_files`).

**Definition of done (verify all at the end):**

- `graider setup --roster r.csv --org swe/2026 --template python --dry-run`
  previews each group with its intended project name and members, fully offline
  (no token, no network).
- A real run creates one project per group, pushes the chosen starter, protects
  `main`, invites members, and writes `graider.lock.json`.
- Project names are `adjective-noun` (optionally `--name-prefix`-tagged) and do
  not collide with existing projects in the org or with each other.
- Re-running `setup` **skips** groups already in the state file and only invites
  members not yet successfully added — no duplicate projects.
- A final Rich summary lists each group, project URL, invited/total members, and
  any accounts that need chasing.
- `uv run ruff check .`, `ruff format --check .`, `ty check`, and `pytest` pass.

---

## Step 1 — Dependencies

None. `json`, `random` are stdlib.

---

## Step 2 — Target file layout

```
src/graider/
├── models.py         # + MemberState, ProjectState, SetupState
├── names.py          # NEW: random adjective-noun names
├── state.py          # NEW: load/save graider.lock.json
├── gitlab_client.py  # + list_group_project_paths()
├── console.py        # + print_project_summary(), print_setup_preview()
└── cli.py            # setup: full orchestration
tests/
├── test_names.py     # NEW
├── test_state.py     # NEW
└── test_cli.py       # + setup orchestration tests (mocked client)
```

---

## Step 3 — `models.py`: state models

Append:

```python
class MemberState(BaseModel):
    email: str
    status: InviteStatus
    username: str | None = None


class ProjectState(BaseModel):
    group_number: str
    name: str
    project_id: int
    web_url: str
    path_with_namespace: str
    template: str
    members: list[MemberState] = []


class SetupState(BaseModel):
    gitlab_url: str = ""
    org: str = ""
    # keyed by group_number
    projects: dict[str, ProjectState] = {}
```

---

## Step 4 — `src/graider/names.py` (NEW)

```python
"""Random, human-friendly project names (adjective-noun)."""

from __future__ import annotations

import random

from graider.errors import GraiderError

ADJECTIVES = [
    "brave", "calm", "clever", "bright", "swift", "quiet", "bold", "eager",
    "gentle", "jolly", "keen", "lively", "merry", "nimble", "proud", "witty",
    "amber", "azure", "crimson", "golden", "silver", "teal", "violet", "coral",
]

NOUNS = [
    "otter", "falcon", "willow", "cedar", "comet", "harbor", "meadow", "raven",
    "maple", "quartz", "lynx", "heron", "birch", "pebble", "summit", "delta",
    "ember", "grove", "marsh", "orbit", "reef", "spruce", "tundra", "vortex",
]


def random_name(taken: set[str], prefix: str = "", rng: random.Random | None = None) -> str:
    """Return an unused `adjective-noun` name (prefixed if given)."""
    rng = rng or random.Random()
    for _ in range(10_000):
        base = f"{rng.choice(ADJECTIVES)}-{rng.choice(NOUNS)}"
        name = f"{prefix}-{base}" if prefix else base
        if name not in taken:
            return name
    raise GraiderError("Could not find a free project name; broaden the word lists.")
```

---

## Step 5 — `src/graider/state.py` (NEW)

```python
"""Read/write the graider.lock.json setup state file."""

from __future__ import annotations

from pathlib import Path

from graider.errors import GraiderError
from graider.models import SetupState


def load_state(path: Path) -> SetupState:
    """Load the state file, or return an empty state if it does not exist."""
    if not path.exists():
        return SetupState()
    try:
        return SetupState.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GraiderError(f"Could not read state file {path}: {exc}") from exc


def save_state(path: Path, state: SetupState) -> None:
    path.write_text(state.model_dump_json(indent=2) + "\n", encoding="utf-8")
```

---

## Step 6 — `gitlab_client.py`: add `list_group_project_paths`

Used for name-collision checks. Add:

```python
    def list_group_project_paths(self, org_path: str) -> set[str]:
        """Return the set of project *paths* already in the group (for collision checks)."""
        try:
            group = self._gl.groups.get(org_path)
            projects = group.projects.list(get_all=True)
        except GitlabError as exc:
            raise GitLabError(f"Could not list projects in {org_path!r}: {exc}") from exc
        return {p.path for p in projects}
```

---

## Step 7 — `console.py`: preview + summary tables

Add imports (extend the existing `from graider.models import ...`):

```python
from graider.models import Group, InviteResult, InviteStatus, SetupState, Student
```

```python
def print_setup_preview(rows: list[tuple[str, str, list[Student]]]) -> None:
    """rows: (group_number, project_name, members)."""
    table = Table(title="Setup preview (dry run)")
    table.add_column("Group", style="bold")
    table.add_column("Project name")
    table.add_column("Members")
    for group_number, name, members in rows:
        emails = "\n".join(s.email for s in members)
        table.add_row(group_number, name, emails)
    console.print(table)


def print_project_summary(state: SetupState) -> None:
    table = Table(title="Projects")
    table.add_column("Group", style="bold")
    table.add_column("Project")
    table.add_column("URL")
    table.add_column("Invited", justify="right")
    table.add_column("Needs account", justify="right")
    for group_number, project in sorted(state.projects.items()):
        ok = sum(
            m.status in (InviteStatus.INVITED, InviteStatus.ALREADY_MEMBER)
            for m in project.members
        )
        missing = sum(m.status == InviteStatus.NO_ACCOUNT for m in project.members)
        table.add_row(
            group_number, project.name, project.web_url,
            f"{ok}/{len(project.members)}", str(missing) or "",
        )
    console.print(table)
```

---

## Step 8 — `cli.py`: full `setup` orchestration

Add imports:

```python
from graider.gitlab_client import GitLabClient
from graider.models import MemberState, ProjectState, SetupState
from graider.names import random_name
from graider.state import load_state, save_state
from graider.console import (
    console, print_error, print_project_summary, print_setup_preview, print_success,
)
from graider.templates import TemplateContext, TemplateName, render_template
```

Replace the whole `setup` command:

```python
@app.command()
def setup(
    ctx: typer.Context,
    roster: Path = typer.Option(
        ..., "--roster", exists=True, dir_okay=False, readable=True,
        help="Roster CSV/XLSX (student emails + group numbers).",
    ),
    org: str = typer.Option(
        "", "--org", help="GitLab group/org full path (e.g. swe/2026). Required unless --dry-run.",
    ),
    template: TemplateName = typer.Option(TemplateName.PYTHON, "--template"),
    course: str = typer.Option("course", "--course"),
    criteria_repo: str = typer.Option("", "--criteria-repo"),
    criteria_path: str = typer.Option("", "--criteria-path"),
    brief_url: str = typer.Option("", "--brief-url"),
    name_prefix: str = typer.Option("", "--name-prefix"),
    state_path: Path = typer.Option(Path("graider.lock.json"), "--state"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Create a GitLab project per group and invite members."""
    config = _config(ctx)
    dry_run = dry_run or config.dry_run

    groups = group_students(read_roster(roster))
    state = load_state(state_path)

    # --- offline preview ---------------------------------------------------
    if dry_run:
        taken = {p.name for p in state.projects.values()}
        rows = []
        for group in groups:
            if group.number in state.projects:
                name = state.projects[group.number].name
            else:
                name = random_name(taken, prefix=name_prefix)
                taken.add(name)
            rows.append((group.number, name, group.members))
        print_setup_preview(rows)
        print_success(f"{len(groups)} groups (dry run, GitLab untouched).")
        return

    # --- real run ----------------------------------------------------------
    if not org:
        raise GraiderError("--org is required (the GitLab group to create projects in).")
    token = require_token(config)

    client = GitLabClient(config.gitlab_url, token)
    client.authenticate()
    namespace_id = client.get_namespace_id(org)
    state.gitlab_url, state.org = config.gitlab_url, org

    taken = client.list_group_project_paths(org) | {p.name for p in state.projects.values()}

    for group in groups:
        if group.number in state.projects:
            _reconcile_members(client, state.projects[group.number], group)
        else:
            name = random_name(taken, prefix=name_prefix)
            taken.add(name)
            ref = client.create_project(name, namespace_id)
            assert ref is not None  # not dry-run here
            context = TemplateContext(
                project_name=name, course=course,
                criteria_repo=criteria_repo, criteria_path=criteria_path,
                brief_url=brief_url,
            )
            client.commit_files(ref.id, render_template(template.value, context))
            client.protect_branch(ref.id, "main")
            members = [
                MemberState(**client.invite_member(ref.id, s.email).model_dump())
                for s in group.members
            ]
            state.projects[group.number] = ProjectState(
                group_number=group.number, name=name, project_id=ref.id,
                web_url=ref.web_url, path_with_namespace=ref.path_with_namespace,
                template=template.value, members=members,
            )
        save_state(state_path, state)  # incremental save = resumable

    print_project_summary(state)
    print_success(f"Set up {len(state.projects)} projects → {state_path}")


def _reconcile_members(client, project, group) -> None:
    """Invite roster members not already successfully added (idempotent re-run)."""
    from graider.models import InviteStatus

    recorded = {m.email: m for m in project.members}
    for student in group.members:
        current = recorded.get(student.email)
        if current and current.status in (InviteStatus.INVITED, InviteStatus.ALREADY_MEMBER):
            continue
        result = client.invite_member(project.project_id, student.email)
        recorded[student.email] = MemberState(**result.model_dump())
    project.members = list(recorded.values())
```

> Notes:
> - `--org` is optional at the Typer level but required for a real run, so the
>   Milestone 2 dry-run tests (which pass no `--org`) keep working.
> - State is saved after **each** group, so a crash mid-run leaves a valid file
>   and the next run resumes.
> - `MemberState(**result.model_dump())` works because `InviteResult` and
>   `MemberState` share the same fields.

---

## Step 9 — Tests

### `tests/test_names.py`

```python
import random

import pytest

from graider.errors import GraiderError
from graider.names import random_name


def test_name_shape():
    name = random_name(set(), rng=random.Random(1))
    assert "-" in name and name.islower()


def test_prefix_applied():
    assert random_name(set(), prefix="swe25", rng=random.Random(1)).startswith("swe25-")


def test_avoids_taken():
    rng = random.Random(0)
    seen = set()
    for _ in range(50):
        name = random_name(seen, rng=rng)
        assert name not in seen
        seen.add(name)


def test_exhaustion_raises(monkeypatch):
    monkeypatch.setattr("graider.names.ADJECTIVES", ["a"])
    monkeypatch.setattr("graider.names.NOUNS", ["b"])
    with pytest.raises(GraiderError):
        random_name({"a-b"})
```

### `tests/test_state.py`

```python
from pathlib import Path

from graider.models import MemberState, ProjectState, SetupState
from graider.models import InviteStatus
from graider.state import load_state, save_state


def test_missing_returns_empty(tmp_path):
    assert load_state(tmp_path / "none.json").projects == {}


def test_round_trip(tmp_path):
    state = SetupState(
        gitlab_url="https://gl", org="swe/2026",
        projects={
            "1": ProjectState(
                group_number="1", name="brave-otter", project_id=7,
                web_url="https://gl/swe/brave-otter",
                path_with_namespace="swe/brave-otter", template="python",
                members=[MemberState(email="a@x.edu", status=InviteStatus.INVITED)],
            )
        },
    )
    path = tmp_path / "graider.lock.json"
    save_state(path, state)
    loaded = load_state(path)
    assert loaded.projects["1"].name == "brave-otter"
    assert loaded.projects["1"].members[0].status == InviteStatus.INVITED
```

### `tests/test_cli.py` — orchestration (mock the client)

```python
from unittest.mock import MagicMock

from graider.models import InviteResult, InviteStatus, ProjectRef


def _fake_client(monkeypatch):
    client = MagicMock()
    client.get_namespace_id.return_value = 100
    client.list_group_project_paths.return_value = set()
    client.create_project.side_effect = lambda name, ns: ProjectRef(
        id=abs(hash(name)) % 1000, name=name,
        path_with_namespace=f"swe/{name}", web_url=f"https://gl/swe/{name}",
    )
    client.invite_member.side_effect = lambda pid, email: InviteResult(
        email=email, status=InviteStatus.INVITED, username=email.split("@")[0]
    )
    monkeypatch.setattr("graider.cli.GitLabClient", lambda *a, **k: client)
    return client


def test_setup_creates_projects_and_state(tmp_path, monkeypatch):
    client = _fake_client(monkeypatch)
    roster = tmp_path / "r.csv"
    roster.write_text("email,group\na@x.edu,1\nb@x.edu,1\nc@x.edu,2\n")
    state_path = tmp_path / "graider.lock.json"
    result = run_cli(
        [*_no_config(tmp_path), "setup", "--roster", str(roster),
         "--org", "swe/2026", "--state", str(state_path)],
        env={"GITLAB_TOKEN": "glpat-x"}, monkeypatch=monkeypatch,
    )
    assert result.exit_code == 0
    assert client.create_project.call_count == 2       # two groups
    assert client.commit_files.call_count == 2
    assert client.invite_member.call_count == 3        # three students
    assert state_path.exists()


def test_setup_is_idempotent(tmp_path, monkeypatch):
    client = _fake_client(monkeypatch)
    roster = tmp_path / "r.csv"
    roster.write_text("email,group\na@x.edu,1\n")
    state_path = tmp_path / "graider.lock.json"
    args = [*_no_config(tmp_path), "setup", "--roster", str(roster),
            "--org", "swe/2026", "--state", str(state_path)]
    run_cli(args, env={"GITLAB_TOKEN": "glpat-x"}, monkeypatch=monkeypatch)
    client.create_project.reset_mock()
    # second run: project already in state -> no new creation
    run_cli(args, env={"GITLAB_TOKEN": "glpat-x"}, monkeypatch=monkeypatch)
    client.create_project.assert_not_called()


def test_setup_dry_run_offline(tmp_path, monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    roster = tmp_path / "r.csv"
    roster.write_text("email,group\na@x.edu,1\n")
    result = run_cli(
        [*_no_config(tmp_path), "--dry-run", "setup", "--roster", str(roster)]
    )
    assert result.exit_code == 0
    assert "dry run" in result.output.lower()
```

---

## Step 10 — Verify

```sh
uv sync
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest -q

printf 'email,group\na@uni.edu,1\nb@uni.edu,1\nc@uni.edu,2\n' > /tmp/r.csv
uv run graider setup --roster /tmp/r.csv --org swe/2026 --template python --dry-run
```

Manual real-run smoke test: against a sandbox org, run without `--dry-run`,
confirm two projects appear with pushed starters and protected `main`, inspect
`graider.lock.json`, then re-run and confirm no new projects are created.

---

## Notes for the next milestones

- The state file is the input to **Milestone 6 (grade)**: teacher mode reads
  `graider.lock.json` to clone/pull every project; student mode uses the
  `.graider.yml` inside a single repo.
- `commit_files` uses `action: "create"`; re-running `setup` currently never
  re-pushes (it skips existing groups), so that's fine here — but if you later
  add a `--force-starter` flag to refresh templates, switch those actions to
  `update` (or detect create-vs-update per file).
- `list_group_project_paths` compares on project `path`; the generated names are
  already valid slugs, so `name == path`. If you add `--name-prefix` with
  characters GitLab slugifies (spaces, capitals), normalize before comparing.
```
