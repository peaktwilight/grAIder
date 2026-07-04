from unittest.mock import MagicMock

import pytest

from graider.feedback.render import REVIEW_MARKER, issue_title, render_feedback
from graider.gitlab_client import GitLabClient
from graider.models import CriterionVerdict, ReviewResult


def _review():
    return ReviewResult(
        project="brave-otter",
        head_sha="abc",
        model="claude-opus-4-8",
        cutoff="2",
        overall_summary="Solid overall.",
        criteria=[
            CriterionVerdict(id="1", title="VCS", met=True, evidence=[], comment="clean"),
            CriterionVerdict(id="2", title="Tests", met=False, evidence=[], comment="add more"),
        ],
    )


def test_render_feedback_marker_and_checklist():
    body = render_feedback(_review())
    assert body.startswith(REVIEW_MARKER)
    assert "1/2 criteria met" in body
    assert "- [x] 1. VCS" in body
    assert "- [ ] 2. Tests — add more" in body


def test_issue_title():
    assert issue_title(_review()) == "grAIder feedback — 2 criteria"


@pytest.fixture
def fake_gl(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr("graider.gitlab_client.gitlab.Gitlab", lambda *a, **k: fake)
    return fake


def test_upsert_mr_note_creates_when_absent(fake_gl):
    mr = fake_gl.projects.get.return_value.mergerequests.get.return_value
    mr.notes.list.return_value = []
    GitLabClient("u", "t").upsert_mr_note(1, 7, "body", REVIEW_MARKER)
    mr.notes.create.assert_called_once_with({"body": "body"})


def test_upsert_mr_note_updates_existing(fake_gl):
    mr = fake_gl.projects.get.return_value.mergerequests.get.return_value
    existing = MagicMock(body=f"old {REVIEW_MARKER}")
    mr.notes.list.return_value = [existing]
    GitLabClient("u", "t").upsert_mr_note(1, 7, "new body", REVIEW_MARKER)
    assert existing.body == "new body"
    existing.save.assert_called_once()
    mr.notes.create.assert_not_called()


def test_upsert_mr_note_dry_run(fake_gl):
    GitLabClient("u", "t", dry_run=True).upsert_mr_note(1, 7, "b", REVIEW_MARKER)
    fake_gl.projects.get.assert_not_called()


def test_upsert_issue_creates(fake_gl):
    project = fake_gl.projects.get.return_value
    project.issues.list.return_value = []
    GitLabClient("u", "t").upsert_issue(1, "Title", "body", REVIEW_MARKER)
    project.issues.create.assert_called_once_with({"title": "Title", "description": "body"})


def test_upsert_issue_updates_existing(fake_gl):
    project = fake_gl.projects.get.return_value
    existing = MagicMock(description=f"x {REVIEW_MARKER}")
    project.issues.list.return_value = [existing]
    GitLabClient("u", "t").upsert_issue(1, "Title", "new", REVIEW_MARKER)
    assert existing.description == "new"
    existing.save.assert_called_once()
    project.issues.create.assert_not_called()


def test_find_open_mr_iid(fake_gl):
    fake_gl.projects.get.return_value.mergerequests.list.return_value = [MagicMock(iid=42)]
    assert GitLabClient("u", "t").find_open_mr_iid(1, "feature") == 42
    fake_gl.projects.get.return_value.mergerequests.list.return_value = []
    assert GitLabClient("u", "t").find_open_mr_iid(1, "feature") is None
