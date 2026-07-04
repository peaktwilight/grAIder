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


# --- E5: backends ---

from graider.review.agent import (  # noqa: E402
    ApiBackend,
    ClaudeCodeBackend,
    _extract_json,
    select_backend,
)


def test_claude_code_backend_parses_json():
    out = ReviewOutput(
        overall_summary="ok",
        criteria=[CriterionVerdict(id="1", title="A", met=True, evidence=[], comment="c")],
    )
    backend = ClaudeCodeBackend(runner=lambda prompt, model: out.model_dump_json())
    result = backend.run("sys", "user", "opus")
    assert result.overall_summary == "ok"


def test_claude_code_backend_extracts_fenced_json():
    out = ReviewOutput(overall_summary="ok", criteria=[])
    fenced = f"```json\n{out.model_dump_json()}\n```"
    backend = ClaudeCodeBackend(runner=lambda prompt, model: fenced)
    assert backend.run("s", "u", "m").overall_summary == "ok"


def test_claude_code_backend_repairs_once():
    out = ReviewOutput(overall_summary="fixed", criteria=[])
    calls = {"n": 0}

    def runner(prompt, model):
        calls["n"] += 1
        return "not json" if calls["n"] == 1 else out.model_dump_json()

    backend = ClaudeCodeBackend(runner=runner)
    assert backend.run("s", "u", "m").overall_summary == "fixed"
    assert calls["n"] == 2


def test_claude_code_backend_gives_up():
    from graider.errors import GraiderError

    backend = ClaudeCodeBackend(runner=lambda prompt, model: "still not json")
    with pytest.raises(GraiderError, match="invalid JSON"):
        backend.run("s", "u", "m")


def test_extract_json_plain_and_fenced():
    assert _extract_json('{"a": 1}') == '{"a": 1}'
    assert _extract_json('prefix {"a": 1} suffix') == '{"a": 1}'


def test_select_backend_explicit():
    assert isinstance(select_backend("api"), ApiBackend)
    assert isinstance(select_backend("claude-code"), ClaudeCodeBackend)


def test_select_backend_auto_prefers_api_with_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    assert isinstance(select_backend("auto"), ApiBackend)
