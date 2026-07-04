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
    result = review_project(tmp_path, "brief", _items(), client=_fake_client(output), model="m")
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
