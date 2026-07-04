"""Agentic (single structured call) review of a repo against criteria."""

from __future__ import annotations

import subprocess
from pathlib import Path

import anthropic

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


def review_project(
    repo_dir: Path,
    brief: str,
    in_scope: list[CriteriaItem],
    *,
    grade: GradeResult | None = None,
    cutoff: str = "",
    model: str = DEFAULT_MODEL,
    client: anthropic.Anthropic | None = None,
) -> ReviewResult:
    client = client or anthropic.Anthropic()
    user_prompt = _build_prompt(brief, in_scope, grade, _collect_files(repo_dir))

    try:
        response = client.messages.parse(
            model=model,
            max_tokens=16000,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
            output_format=ReviewOutput,
        )
    except Exception as exc:  # wrap SDK/auth/network errors into a clean message
        raise GraiderError(
            f"AI review failed ({exc}). Check your Anthropic credentials "
            "(set ANTHROPIC_API_KEY or run `ant auth login`)."
        ) from exc

    output = response.parsed_output
    if output is None:
        raise GraiderError("AI review response could not be parsed.")
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
