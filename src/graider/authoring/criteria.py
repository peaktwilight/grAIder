"""Teacher authoring: draft criteria from a syllabus, and validate a criteria repo."""

from __future__ import annotations

import base64
from pathlib import Path

import anthropic

from graider.criteria import load_criteria_dir, released_cutoff
from graider.errors import GraiderError
from graider.models import CriteriaDraft

DEFAULT_MODEL = "claude-opus-4-8"

_SYSTEM = (
    "You are a university teaching assistant. From the given syllabus, extract "
    "the topics students are graded on, in teaching order. Produce an ordered "
    "list of grading criteria: one item per topic, each with a short title and a "
    "body describing what to check plus 2-3 concrete evaluation questions a "
    "grader would ask. Also write a one-paragraph project brief."
)


def draft_criteria(
    syllabus: Path,
    *,
    model: str = DEFAULT_MODEL,
    client: anthropic.Anthropic | None = None,
) -> CriteriaDraft:
    if not syllabus.exists():
        raise GraiderError(f"Syllabus not found: {syllabus}")
    client = client or anthropic.Anthropic()
    content = _syllabus_content(syllabus)
    try:
        response = client.messages.parse(
            model=model,
            max_tokens=16000,
            system=_SYSTEM,
            # Document/text content blocks are valid at runtime; ty is over-strict
            # on the SDK's nested content-block TypedDict union.
            messages=[{"role": "user", "content": content}],  # ty: ignore[invalid-argument-type]
            output_format=CriteriaDraft,
        )
    except Exception as exc:
        raise GraiderError(
            f"Criteria drafting failed ({exc}). Check your Anthropic credentials "
            "(set ANTHROPIC_API_KEY or run `ant auth login`)."
        ) from exc
    draft = response.parsed_output
    if draft is None or not draft.items:
        raise GraiderError("The model returned no criteria items.")
    return draft


def _syllabus_content(syllabus: Path) -> list[dict]:
    if syllabus.suffix.lower() == ".pdf":
        data = base64.standard_b64encode(syllabus.read_bytes()).decode("ascii")
        return [
            {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": data},
            },
            {"type": "text", "text": "Draft grading criteria from this syllabus."},
        ]
    text = syllabus.read_text(encoding="utf-8")
    return [{"type": "text", "text": f"Syllabus:\n\n{text}"}]


def write_criteria_dir(draft: CriteriaDraft, out_dir: Path, *, force: bool = False) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = out_dir / "criteria.md"
    cutoff = out_dir / "graider-criteria.yml"
    if not force and (doc.exists() or cutoff.exists()):
        raise GraiderError(f"{out_dir} already has criteria files; pass --force to overwrite.")

    lines = ["# Project Brief", "", draft.brief.strip(), "", "# Criteria", ""]
    for index, item in enumerate(draft.items, start=1):
        lines += [f"## {index}. {item.title.strip()}", "", item.body.strip(), ""]
    doc.write_text("\n".join(lines), encoding="utf-8")
    cutoff.write_text("released_up_to: 0\n", encoding="utf-8")


def check_criteria_dir(criteria_dir: Path) -> list[str]:
    problems: list[str] = []
    try:
        criteria = load_criteria_dir(criteria_dir)
    except GraiderError as exc:
        return [str(exc)]

    if not criteria.items:
        problems.append("no criteria items found")
    ids = [item.id for item in criteria.items]
    if len(ids) != len(set(ids)):
        problems.append(f"duplicate criteria ids: {sorted(i for i in ids if ids.count(i) > 1)}")
    for expected, item in enumerate(criteria.items, start=1):
        if item.order != expected:
            problems.append(f"item {item.id!r} has order {item.order}, expected {expected}")

    cutoff = released_cutoff(criteria_dir)
    if cutoff is None:
        problems.append("missing graider-criteria.yml (released_up_to)")
    elif str(cutoff).isdigit():
        if not (0 <= int(cutoff) <= len(criteria.items)):
            problems.append(f"released_up_to {cutoff} out of range 0..{len(criteria.items)}")
    elif str(cutoff) not in ids:
        problems.append(f"released_up_to {cutoff!r} matches no item id")
    return problems
