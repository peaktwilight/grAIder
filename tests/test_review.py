from unittest.mock import MagicMock

import pytest

from graider.errors import GraiderError
from graider.models import CriteriaItem, CriterionVerdict, ReviewOutput
from graider.review.agent import _build_prompt, _collect_files, review_project
from graider.review.cache import ReviewCache


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
    GeminiBackend,
    OpenAICompatBackend,
    _extract_json,
    select_backend,
)


def test_claude_code_backend_parses_json():
    out = ReviewOutput(
        overall_summary="ok",
        criteria=[CriterionVerdict(id="1", title="A", met=True, evidence=[], comment="c")],
    )
    backend = ClaudeCodeBackend(runner=lambda prompt, model: out.model_dump_json())
    result = backend.run("sys", "user", "opus", ReviewOutput)
    assert result.overall_summary == "ok"


def test_claude_code_backend_extracts_fenced_json():
    out = ReviewOutput(overall_summary="ok", criteria=[])
    fenced = f"```json\n{out.model_dump_json()}\n```"
    backend = ClaudeCodeBackend(runner=lambda prompt, model: fenced)
    assert backend.run("s", "u", "m", ReviewOutput).overall_summary == "ok"


def test_claude_code_backend_repairs_once():
    out = ReviewOutput(overall_summary="fixed", criteria=[])
    calls = {"n": 0}

    def runner(prompt, model):
        calls["n"] += 1
        return "not json" if calls["n"] == 1 else out.model_dump_json()

    backend = ClaudeCodeBackend(runner=runner)
    assert backend.run("s", "u", "m", ReviewOutput).overall_summary == "fixed"
    assert calls["n"] == 2


def test_claude_code_backend_gives_up():
    from graider.errors import GraiderError

    backend = ClaudeCodeBackend(runner=lambda prompt, model: "still not json")
    with pytest.raises(GraiderError, match="invalid JSON"):
        backend.run("s", "u", "m", ReviewOutput)


def test_extract_json_plain_and_fenced():
    assert _extract_json('{"a": 1}') == '{"a": 1}'
    assert _extract_json('prefix {"a": 1} suffix') == '{"a": 1}'


def test_select_backend_explicit():
    assert isinstance(select_backend("api"), ApiBackend)
    assert isinstance(select_backend("claude-code"), ClaudeCodeBackend)


def test_select_backend_auto_prefers_api_with_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    assert isinstance(select_backend("auto"), ApiBackend)


def _openai_client(payload: str):
    message = MagicMock()
    message.content = payload
    choice = MagicMock()
    choice.message = message
    resp = MagicMock()
    resp.choices = [choice]
    client = MagicMock()
    client.chat.completions.create.return_value = resp
    return client


def test_openai_backend_parses_json():
    out = ReviewOutput(overall_summary="ok", criteria=[])
    backend = OpenAICompatBackend(client=_openai_client(out.model_dump_json()))
    assert backend.run("sys", "user", "gpt-x", ReviewOutput).overall_summary == "ok"


def test_openai_backend_rejects_pdf():
    backend = OpenAICompatBackend(client=_openai_client("{}"))
    with pytest.raises(GraiderError, match="text prompts"):
        backend.run("s", [{"type": "document"}], "gpt-x", ReviewOutput)


def test_gemini_backend_returns_parsed():
    out = ReviewOutput(overall_summary="ok", criteria=[])
    client = MagicMock()
    client.models.generate_content.return_value = MagicMock(parsed=out)
    backend = GeminiBackend(client=client)
    assert backend.run("sys", "user", "gemini-x", ReviewOutput).overall_summary == "ok"


def test_select_backend_multi_provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setenv("GLM_API_KEY", "glm-x")
    monkeypatch.setenv("GEMINI_API_KEY", "g-x")
    assert isinstance(select_backend("openai"), OpenAICompatBackend)
    assert isinstance(select_backend("glm"), OpenAICompatBackend)
    assert isinstance(select_backend("gemini"), GeminiBackend)


def test_select_backend_unknown_raises():
    with pytest.raises(GraiderError, match="Unknown backend"):
        select_backend("bogus")


def test_api_backend_captures_usage():
    from graider.models import Usage

    out = ReviewOutput(overall_summary="ok", criteria=[])
    client = MagicMock()
    resp = MagicMock(parsed_output=out)
    resp.usage.input_tokens = 12
    resp.usage.output_tokens = 34
    client.messages.parse.return_value = resp
    backend = ApiBackend(client=client)
    backend.run("s", "u", "m", ReviewOutput)
    assert backend.last_usage == Usage(input_tokens=12, output_tokens=34)


def test_openai_backend_captures_usage():
    from graider.models import Usage

    out = ReviewOutput(overall_summary="ok", criteria=[])
    client = _openai_client(out.model_dump_json())
    resp = client.chat.completions.create.return_value
    resp.usage.prompt_tokens = 5
    resp.usage.completion_tokens = 7
    backend = OpenAICompatBackend(client=client)
    backend.run("s", "u", "m", ReviewOutput)
    assert backend.last_usage == Usage(input_tokens=5, output_tokens=7)


def test_gemini_backend_captures_usage():
    from graider.models import Usage

    out = ReviewOutput(overall_summary="ok", criteria=[])
    client = MagicMock()
    resp = MagicMock(parsed=out)
    resp.usage_metadata.prompt_token_count = 8
    resp.usage_metadata.candidates_token_count = 9
    client.models.generate_content.return_value = resp
    backend = GeminiBackend(client=client)
    backend.run("s", "u", "m", ReviewOutput)
    assert backend.last_usage == Usage(input_tokens=8, output_tokens=9)


class _CountingBackend:
    last_usage = None

    def __init__(self, output):
        self._output = output
        self.calls = 0

    def run(self, system, user_prompt, model, output_format):
        self.calls += 1
        return self._output


def test_review_cache_hit_skips_backend(tmp_path):
    (tmp_path / "main.py").write_text("print(1)\n")
    out = ReviewOutput(overall_summary="Solid.", criteria=[])
    backend = _CountingBackend(out)
    cache = ReviewCache.load(tmp_path / "r.cache.json")
    review_project(tmp_path, "brief", _items(), backend=backend, model="m", cache=cache)
    review_project(tmp_path, "brief", _items(), backend=backend, model="m", cache=cache)
    assert backend.calls == 1
    assert cache.last_hit is True


def test_review_cache_invalidated_by_model(tmp_path):
    (tmp_path / "main.py").write_text("print(1)\n")
    out = ReviewOutput(overall_summary="Solid.", criteria=[])
    backend = _CountingBackend(out)
    cache = ReviewCache.load(tmp_path / "r.cache.json")
    review_project(tmp_path, "brief", _items(), backend=backend, model="m1", cache=cache)
    review_project(tmp_path, "brief", _items(), backend=backend, model="m2", cache=cache)
    assert backend.calls == 2


def test_review_cache_refresh_bypasses_hit(tmp_path):
    (tmp_path / "main.py").write_text("print(1)\n")
    out = ReviewOutput(overall_summary="Solid.", criteria=[])
    backend = _CountingBackend(out)
    cache = ReviewCache.load(tmp_path / "r.cache.json")
    review_project(tmp_path, "brief", _items(), backend=backend, model="m", cache=cache)
    review_project(
        tmp_path, "brief", _items(), backend=backend, model="m", cache=cache, refresh=True
    )
    assert backend.calls == 2


def test_review_cache_persists_across_load(tmp_path):
    (tmp_path / "main.py").write_text("print(1)\n")
    out = ReviewOutput(overall_summary="Solid.", criteria=[])
    backend = _CountingBackend(out)
    path = tmp_path / "r.cache.json"
    review_project(
        tmp_path, "brief", _items(), backend=backend, model="m", cache=ReviewCache.load(path)
    )
    fresh = ReviewCache.load(path)
    review_project(tmp_path, "brief", _items(), backend=backend, model="m", cache=fresh)
    assert backend.calls == 1
    assert fresh.last_hit is True
