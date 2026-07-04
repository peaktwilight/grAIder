# Milestone 3 — Detailed Implementation Plan

**Goal:** a thin, unit-tested wrapper around `python-gitlab` that can resolve a
target group/org, create a project, look up users by email, invite members, and
protect a branch — with every student's invite classified as
`invited` / `already_member` / `no_account`, and all writes gated behind
`--dry-run`.

This document is prescriptive. Follow the steps in order. Where full code is
given, you may copy it verbatim.

**Scope boundary:** this milestone builds the client **library** only. It adds
no new CLI surface — wiring `setup` to actually create projects and persist a
state file is Milestone 5. Verification here is mocked unit tests plus an
optional manual smoke test against a sandbox group.

**Definition of done (verify all at the end):**

- `GitLabClient` exposes `authenticate`, `get_namespace_id`, `create_project`,
  `find_user_by_email`, `invite_member`, `protect_branch`.
- `invite_member` returns an `InviteResult` whose status is one of
  `invited` / `already_member` / `no_account` (real run) or `skipped` (dry run).
- In `dry_run=True`, **no** mutating **or** networked call is made (consistent
  with Milestone 2's offline dry-run). Tests assert the API was not called.
- Bad token → `authenticate()` raises a clean `GitLabError` (a `GraiderError`,
  so the CLI shows it without a traceback).
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`, and
  `uv run pytest` all pass, with **no real network access** in the test suite.

---

## Step 1 — Add the python-gitlab dependency

Edit `pyproject.toml`, under `[project]` add one line to `dependencies`:

```toml
dependencies = [
    "typer>=0.12",
    "rich>=13.7",
    "pydantic>=2.7",
    "openpyxl>=3.1",
    "python-gitlab>=4.4",
]
```

Then:

```sh
uv sync
```

---

## Step 2 — Target file layout

```
src/graider/
├── errors.py         # + GitLabError
├── models.py         # + InviteStatus, InviteResult, ProjectRef
├── gitlab_client.py  # NEW: GitLabClient wrapper
└── console.py        # + print_invite_results()
tests/
└── test_gitlab_client.py   # NEW (fully mocked, no network)
```

---

## Step 3 — `errors.py`: add `GitLabError`

Append (keep existing classes):

```python
class GitLabError(GraiderError):
    """A GitLab API call failed or returned an unexpected result."""
```

---

## Step 4 — `models.py`: add invite/project models

Append to `models.py`. Add `from enum import StrEnum` to the imports at the top.

```python
class InviteStatus(StrEnum):
    INVITED = "invited"
    ALREADY_MEMBER = "already_member"
    NO_ACCOUNT = "no_account"
    SKIPPED = "skipped"  # dry run only


class InviteResult(BaseModel):
    email: str
    status: InviteStatus
    username: str | None = None


class ProjectRef(BaseModel):
    id: int
    name: str
    path_with_namespace: str
    web_url: str
```

> These are plain pydantic models (no GitLab imports) so Milestone 5 can persist
> them straight into the state file.

---

## Step 5 — `src/graider/gitlab_client.py` (NEW)

### Behavior

- Construct `gitlab.Gitlab(url, private_token=token, retry_transient_errors=True)`.
  `retry_transient_errors=True` retries 5xx; `obey_rate_limit=True` (the default)
  handles HTTP 429 — that is the retry/rate-limit handling.
- Every python-gitlab exception is caught and re-raised as `GitLabError` with a
  clean, user-facing message.
- **Dry-run is fully offline:** `create_project` returns `None`, `invite_member`
  returns `SKIPPED`, and `protect_branch` is a no-op — none of them touch the
  network. This matches Milestone 2, where `--dry-run` needs no token.
- `invite_member` on a real run: look up the user by email; if not found →
  `no_account`; if found and added → `invited`; if the API reports a 409
  conflict → `already_member`.

### Full code

```python
"""Thin wrapper around python-gitlab for the operations graider needs."""

from __future__ import annotations

from collections.abc import Iterator

import gitlab
from gitlab.const import AccessLevel
from gitlab.exceptions import (
    GitlabAuthenticationError,
    GitlabCreateError,
    GitlabError,
    GitlabGetError,
)

from graider.errors import GitLabError
from graider.models import InviteResult, InviteStatus, ProjectRef


class GitLabClient:
    def __init__(self, url: str, token: str, *, dry_run: bool = False) -> None:
        self._gl = gitlab.Gitlab(
            url=url, private_token=token, retry_transient_errors=True
        )
        self.dry_run = dry_run

    def authenticate(self) -> None:
        """Validate the token. Raises GitLabError on failure."""
        try:
            self._gl.auth()
        except GitlabAuthenticationError as exc:
            raise GitLabError(f"GitLab authentication failed: {exc}") from exc

    def get_namespace_id(self, org_path: str) -> int:
        """Resolve a group/org full path (e.g. 'swe/2026') to its numeric id."""
        try:
            group = self._gl.groups.get(org_path)
        except GitlabGetError as exc:
            raise GitLabError(
                f"GitLab group/org not found: {org_path!r} ({exc})"
            ) from exc
        return group.id

    def create_project(
        self, name: str, namespace_id: int, *, visibility: str = "private"
    ) -> ProjectRef | None:
        """Create a project under a namespace. Returns None in dry-run."""
        if self.dry_run:
            return None
        try:
            project = self._gl.projects.create(
                {"name": name, "namespace_id": namespace_id, "visibility": visibility}
            )
        except GitlabCreateError as exc:
            raise GitLabError(f"Could not create project {name!r}: {exc}") from exc
        return ProjectRef(
            id=project.id,
            name=project.name,
            path_with_namespace=project.path_with_namespace,
            web_url=project.web_url,
        )

    def find_user_by_email(self, email: str) -> object | None:
        """Return the GitLab user matching email, or None.

        Note: for a non-admin token GitLab only matches a user's *public* email,
        so users without a public email fall into `no_account`. Use an admin
        token (or ask students to make their email public) for reliable lookup.
        """
        target = email.strip().lower()
        try:
            matches = self._gl.users.list(search=email, get_all=True)
        except GitlabError as exc:
            raise GitLabError(f"User lookup failed for {email!r}: {exc}") from exc
        for user in matches:
            if target in set(_user_emails(user)):
                return user
        return None

    def invite_member(
        self,
        project_id: int,
        email: str,
        access_level: AccessLevel = AccessLevel.DEVELOPER,
    ) -> InviteResult:
        if self.dry_run:
            return InviteResult(email=email, status=InviteStatus.SKIPPED)

        user = self.find_user_by_email(email)
        if user is None:
            return InviteResult(email=email, status=InviteStatus.NO_ACCOUNT)

        project = self._gl.projects.get(project_id, lazy=True)
        try:
            project.members.create(
                {"user_id": user.id, "access_level": int(access_level)}
            )
        except GitlabCreateError as exc:
            if exc.response_code == 409:  # already a member
                return InviteResult(
                    email=email,
                    status=InviteStatus.ALREADY_MEMBER,
                    username=user.username,
                )
            raise GitLabError(
                f"Could not add {email} to project {project_id}: {exc}"
            ) from exc
        return InviteResult(
            email=email, status=InviteStatus.INVITED, username=user.username
        )

    def protect_branch(self, project_id: int, branch: str = "main") -> None:
        """Protect a branch. No-op in dry-run; ignores 'already protected'."""
        if self.dry_run:
            return
        project = self._gl.projects.get(project_id, lazy=True)
        try:
            project.protectedbranches.create({"name": branch})
        except GitlabCreateError as exc:
            if exc.response_code == 409:  # already protected
                return
            raise GitLabError(
                f"Could not protect branch {branch!r} on project {project_id}: {exc}"
            ) from exc


def _user_emails(user: object) -> Iterator[str]:
    """Yield the string email attributes present on a user object.

    Guards with isinstance so it works for both real python-gitlab objects and
    MagicMock test doubles (whose unset attributes are Mocks, not strings).
    """
    for attr in ("email", "public_email"):
        value = getattr(user, attr, None)
        if isinstance(value, str) and value:
            yield value.lower()
```

---

## Step 6 — `console.py`: add `print_invite_results`

Append. `InviteResult`/`InviteStatus` come from `models` (already importable).

```python
from graider.models import Group, InviteResult, InviteStatus  # extend existing import
```

```python
_INVITE_STYLE = {
    InviteStatus.INVITED: ("[green]✓ invited[/]", ""),
    InviteStatus.ALREADY_MEMBER: ("[dim]• already a member[/]", ""),
    InviteStatus.NO_ACCOUNT: ("[yellow]! no GitLab account[/]", ""),
    InviteStatus.SKIPPED: ("[dim]— skipped (dry run)[/]", ""),
}


def print_invite_results(results: list[InviteResult]) -> None:
    table = Table(title="Invitations")
    table.add_column("Email")
    table.add_column("Status")
    table.add_column("Username")
    for result in results:
        label, _ = _INVITE_STYLE.get(result.status, (result.status.value, ""))
        table.add_row(result.email, label, result.username or "")
    console.print(table)
```

> This renderer is what the manual smoke test and Milestone 5 use to show the
> instructor who got in and who needs chasing.

---

## Step 7 — `tests/test_gitlab_client.py` (NEW, fully mocked)

Patch `graider.gitlab_client.gitlab.Gitlab` so **no real network** is used.

```python
from unittest.mock import MagicMock

import pytest
from gitlab.exceptions import GitlabAuthenticationError, GitlabCreateError, GitlabGetError

from graider.errors import GitLabError
from graider.gitlab_client import GitLabClient
from graider.models import InviteStatus


@pytest.fixture
def fake_gl(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(
        "graider.gitlab_client.gitlab.Gitlab", lambda *a, **k: fake
    )
    return fake


def _user(**kw):
    # Force attrs to real values; unset ones stay Mocks (filtered by isinstance).
    u = MagicMock()
    for k, v in kw.items():
        setattr(u, k, v)
    return u


# --- auth --------------------------------------------------------------------


def test_authenticate_ok(fake_gl):
    GitLabClient("https://gl", "t").authenticate()
    fake_gl.auth.assert_called_once()


def test_authenticate_bad_token(fake_gl):
    fake_gl.auth.side_effect = GitlabAuthenticationError("401")
    with pytest.raises(GitLabError, match="authentication failed"):
        GitLabClient("https://gl", "t").authenticate()


# --- namespace ---------------------------------------------------------------


def test_get_namespace_id(fake_gl):
    fake_gl.groups.get.return_value = MagicMock(id=99)
    assert GitLabClient("https://gl", "t").get_namespace_id("org/sub") == 99


def test_get_namespace_missing(fake_gl):
    fake_gl.groups.get.side_effect = GitlabGetError("404")
    with pytest.raises(GitLabError, match="not found"):
        GitLabClient("https://gl", "t").get_namespace_id("nope")


# --- create project ----------------------------------------------------------


def test_create_project(fake_gl):
    fake_gl.projects.create.return_value = MagicMock(
        id=42, name="proj", path_with_namespace="org/proj",
        web_url="https://gl/org/proj",
    )
    ref = GitLabClient("https://gl", "t").create_project("proj", 5)
    assert ref.id == 42
    assert ref.web_url == "https://gl/org/proj"
    fake_gl.projects.create.assert_called_once()


def test_create_project_dry_run(fake_gl):
    assert GitLabClient("https://gl", "t", dry_run=True).create_project("p", 5) is None
    fake_gl.projects.create.assert_not_called()


# --- invite ------------------------------------------------------------------


def test_invite_no_account(fake_gl):
    fake_gl.users.list.return_value = []
    result = GitLabClient("https://gl", "t").invite_member(1, "ghost@x.edu")
    assert result.status == InviteStatus.NO_ACCOUNT


def test_invite_new_member(fake_gl):
    fake_gl.users.list.return_value = [_user(id=7, username="ada", email="ada@x.edu")]
    result = GitLabClient("https://gl", "t").invite_member(1, "ada@x.edu")
    assert result.status == InviteStatus.INVITED
    assert result.username == "ada"
    fake_gl.projects.get.return_value.members.create.assert_called_once()


def test_invite_already_member(fake_gl):
    fake_gl.users.list.return_value = [_user(id=7, username="ada", email="ada@x.edu")]
    fake_gl.projects.get.return_value.members.create.side_effect = GitlabCreateError(
        "conflict", response_code=409
    )
    result = GitLabClient("https://gl", "t").invite_member(1, "ada@x.edu")
    assert result.status == InviteStatus.ALREADY_MEMBER


def test_invite_email_match_is_case_insensitive(fake_gl):
    fake_gl.users.list.return_value = [_user(id=7, username="ada", email="Ada@X.edu")]
    result = GitLabClient("https://gl", "t").invite_member(1, "ada@x.edu")
    assert result.status == InviteStatus.INVITED


def test_invite_dry_run_is_offline(fake_gl):
    result = GitLabClient("https://gl", "t", dry_run=True).invite_member(1, "a@x.edu")
    assert result.status == InviteStatus.SKIPPED
    fake_gl.users.list.assert_not_called()
    fake_gl.projects.get.assert_not_called()


# --- protect branch ----------------------------------------------------------


def test_protect_branch(fake_gl):
    GitLabClient("https://gl", "t").protect_branch(1, "main")
    fake_gl.projects.get.return_value.protectedbranches.create.assert_called_once()


def test_protect_branch_already_protected(fake_gl):
    fake_gl.projects.get.return_value.protectedbranches.create.side_effect = (
        GitlabCreateError("exists", response_code=409)
    )
    # Should not raise.
    GitLabClient("https://gl", "t").protect_branch(1, "main")


def test_protect_branch_dry_run(fake_gl):
    GitLabClient("https://gl", "t", dry_run=True).protect_branch(1, "main")
    fake_gl.projects.get.assert_not_called()
```

> `GitlabCreateError("msg", response_code=409)` — python-gitlab's error accepts
> `response_code` as a keyword. If a version mismatch makes `.response_code`
> absent, set it explicitly on the instance in the test.

---

## Step 8 — Manual smoke test (optional, not committed)

Against a real sandbox group you control, in a REPL or a throwaway script under
`scratch/` (gitignored):

```python
from graider.gitlab_client import GitLabClient
from graider.console import print_invite_results

c = GitLabClient("https://gitlab.com", "<your-token>")
c.authenticate()
ns = c.get_namespace_id("your-sandbox-group")
proj = c.create_project("graider-smoke-test", ns)
print(proj.web_url)
res = [c.invite_member(proj.id, "someone@example.com")]
print_invite_results(res)
```

Delete the test project afterwards. Do not commit tokens or the script.

---

## Step 9 — Verify

```sh
uv sync
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest -q        # all green, no network
```

If `ruff format --check` fails, run `uv run ruff format .` and re-check.

---

## Caveats to know

- **Email lookup needs a public email or an admin token.** GitLab's user search
  only matches a *public* email for non-admin tokens. Students whose email is
  private will show as `no_account` even if they have an account. Document this
  for instructors; the `no_account` list is a "verify these manually" list, not
  a hard "these people don't exist" claim.
- **Alternative for zero-account invites (future):** GitLab supports pending
  email invitations via `project.invitations.create({"email", "access_level"})`
  that work without resolving a user. We deliberately don't use that here
  because the requirement is to *report* who has no account. Revisit if you'd
  rather auto-invite everyone and reconcile later.

---

## Notes for the next milestones

- **Milestone 4 (templates)** adds the starter code + `qlty.toml` + `.graider.yml`
  and pushes them via the commit API; `protect_branch` is called *after* that
  push (an empty repo has no branch to protect yet).
- **Milestone 5 (orchestration)** constructs one `GitLabClient`, calls
  `authenticate()` once, resolves `--org` to a namespace id, then per group:
  `create_project` → push starter → `protect_branch` → `invite_member` for each
  member. It collects the `InviteResult`s and `ProjectRef`s into the state file
  (`graider.lock.json`) and prints `print_invite_results`. That is where the
  "recorded in the state file so instructors can chase missing accounts"
  requirement is satisfied — `InviteResult` is already serializable for it.
```
