"""Agentic (single structured call) review of a repo against criteria.

Two backends run the model: `ApiBackend` (anthropic SDK, API-key billing) and
`ClaudeCodeBackend` (the Claude Code CLI in headless mode, subscription billing).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Protocol

import anthropic
from pydantic import ValidationError

from graider.errors import GraiderError
from graider.models import CriteriaItem, GradeResult, ReviewOutput, ReviewResult

DEFAULT_MODEL = "claude-opus-4-8"
_MAX_TOTAL_BYTES = 200_000
_SKIP_DIRS = {".git", "build", ".venv", "venv", "node_modules", "__pycache__", ".qlty"}
_TEXT_SUFFIXES = {
    ".py",
    ".java",
    ".kt",
    ".kts",
    ".cpp",
    ".hpp",
    ".h",
    ".c",
    ".cc",
    ".md",
    ".txt",
    ".toml",
    ".cfg",
    ".yml",
    ".yaml",
    ".cmake",
    ".gradle",
}

_SYSTEM = (
    "You are a strict but fair programming-course grader. Evaluate the student "
    "repository against each provided criterion. For each criterion decide met "
    "(true/false), cite concrete evidence as 'path:line — note', and keep "
    "comments short and actionable. Judge only the criteria you are given."
)


class ReviewBackend(Protocol):
    def run(self, system: str, user_prompt: str, model: str) -> ReviewOutput: ...


class ApiBackend:
    """Structured-output call via the anthropic SDK (API key billing)."""

    def __init__(self, client: anthropic.Anthropic | None = None) -> None:
        self._client = client

    def run(self, system: str, user_prompt: str, model: str) -> ReviewOutput:
        client = self._client or anthropic.Anthropic()
        try:
            response = client.messages.parse(
                model=model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": user_prompt}],
                output_format=ReviewOutput,
            )
        except Exception as exc:
            raise GraiderError(
                f"AI review failed ({exc}). Check your Anthropic credentials "
                "(set ANTHROPIC_API_KEY or run `ant auth login`)."
            ) from exc
        output = response.parsed_output
        if output is None:
            raise GraiderError("AI review response could not be parsed.")
        return output


class ClaudeCodeBackend:
    """Run the review through the Claude Code CLI headless mode (subscription).

    `runner(prompt, model) -> str` is injectable for tests; the default shells
    out to `claude -p ... --output-format json`.
    """

    def __init__(self, runner=None) -> None:
        self._runner = runner or _run_claude

    def run(self, system: str, user_prompt: str, model: str) -> ReviewOutput:
        schema = json.dumps(ReviewOutput.model_json_schema())
        prompt = (
            f"{system}\n\nReturn ONLY minified JSON matching this JSON schema, "
            f"with no prose or markdown fences:\n{schema}\n\n{user_prompt}"
        )
        text = self._runner(prompt, model)
        try:
            return ReviewOutput.model_validate_json(_extract_json(text))
        except (ValidationError, ValueError):
            repair = (
                "Your previous reply was not valid JSON for the schema. "
                "Reply with ONLY the JSON object, nothing else."
            )
            text = self._runner(f"{prompt}\n\n{repair}", model)
            try:
                return ReviewOutput.model_validate_json(_extract_json(text))
            except (ValidationError, ValueError) as exc:
                raise GraiderError(f"Claude Code returned invalid JSON: {exc}") from exc


def select_backend(name: str, *, client: anthropic.Anthropic | None = None) -> ReviewBackend:
    """Pick a backend: 'api', 'claude-code', or 'auto'."""
    if name == "api":
        return ApiBackend(client=client)
    if name == "claude-code":
        return ClaudeCodeBackend()
    # auto: prefer the subscription CLI when present and no API key is set.
    if shutil.which("claude") and not os.environ.get("ANTHROPIC_API_KEY"):
        return ClaudeCodeBackend()
    return ApiBackend(client=client)


def _run_claude(prompt: str, model: str) -> str:
    if not shutil.which("claude"):
        raise GraiderError(
            "Claude Code CLI not found; install it and run `claude login`, "
            "or use --backend api with an ANTHROPIC_API_KEY."
        )
    proc = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "json", "--model", model],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise GraiderError(
            f"Claude Code failed ({proc.stderr.strip() or 'is it logged in? run `claude login`'})."
        )
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise GraiderError(f"Claude Code output was not JSON: {exc}") from exc
    if envelope.get("is_error"):
        raise GraiderError(f"Claude Code error: {envelope.get('result')}")
    return str(envelope.get("result", ""))


def _extract_json(text: str) -> str:
    """Pull the JSON object out of a model reply (tolerate fences/prose)."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("\n") + 1 :] if "\n" in text else text
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in reply")
    return text[start : end + 1]


def review_project(
    repo_dir: Path,
    brief: str,
    in_scope: list[CriteriaItem],
    *,
    grade: GradeResult | None = None,
    cutoff: str = "",
    model: str = DEFAULT_MODEL,
    backend: ReviewBackend | None = None,
    client: anthropic.Anthropic | None = None,
) -> ReviewResult:
    backend = backend or ApiBackend(client=client)
    user_prompt = _build_prompt(brief, in_scope, grade, _collect_files(repo_dir))
    output = backend.run(_SYSTEM, user_prompt, model)
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
        capture_output=True,
        text=True,
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
    parts = [
        f"# Project brief\n{brief or '(none provided)'}",
        "\n# Criteria to evaluate",
    ]
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
