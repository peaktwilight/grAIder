from unittest.mock import MagicMock

import pytest
from gitlab.exceptions import GitlabAuthenticationError, GitlabCreateError, GitlabGetError

from graider.errors import GitLabError
from graider.gitlab_client import GitLabClient
from graider.models import InviteStatus, RenderedFile


@pytest.fixture
def fake_gl(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr("graider.gitlab_client.gitlab.Gitlab", lambda *a, **k: fake)
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
    proj = MagicMock()
    proj.id = 42
    proj.name = "proj"
    proj.path_with_namespace = "org/proj"
    proj.web_url = "https://gl/org/proj"
    fake_gl.projects.create.return_value = proj
    ref = GitLabClient("https://gl", "t").create_project("proj", 5)
    assert ref is not None
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
    fake_gl.projects.get.return_value.protectedbranches.create.side_effect = GitlabCreateError(
        "exists", response_code=409
    )
    # Should not raise.
    GitLabClient("https://gl", "t").protect_branch(1, "main")


def test_protect_branch_dry_run(fake_gl):
    GitLabClient("https://gl", "t", dry_run=True).protect_branch(1, "main")
    fake_gl.projects.get.assert_not_called()


def test_commit_files(fake_gl):
    files = [
        RenderedFile(path=".graider.yml", content="a"),
        RenderedFile(path="src/calc.py", content="b"),
    ]
    GitLabClient("https://gl", "t").commit_files(1, files)
    payload = fake_gl.projects.get.return_value.commits.create.call_args[0][0]
    assert payload["branch"] == "main"
    assert {a["file_path"] for a in payload["actions"]} == {".graider.yml", "src/calc.py"}
    assert all(a["action"] == "create" for a in payload["actions"])


def test_commit_files_dry_run(fake_gl):
    files = [RenderedFile(path="x", content="y")]
    GitLabClient("https://gl", "t", dry_run=True).commit_files(1, files)
    fake_gl.projects.get.assert_not_called()
