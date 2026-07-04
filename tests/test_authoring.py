from unittest.mock import MagicMock

import pytest

from graider.authoring.criteria import (
    check_criteria_dir,
    draft_criteria,
    write_criteria_dir,
)
from graider.criteria import load_criteria_dir
from graider.errors import GraiderError
from graider.models import CriteriaDraft, DraftItem
from graider.review.agent import ApiBackend


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
    draft = draft_criteria(syllabus, backend=ApiBackend(client=client))
    assert len(draft.items) == 2


def test_draft_wraps_sdk_errors(tmp_path):
    syllabus = tmp_path / "s.md"
    syllabus.write_text("x")
    client = MagicMock()
    client.messages.parse.side_effect = RuntimeError("401")
    with pytest.raises(GraiderError, match="Anthropic credentials"):
        draft_criteria(syllabus, backend=ApiBackend(client=client))


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
