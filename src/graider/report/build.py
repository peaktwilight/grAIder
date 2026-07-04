"""Merge grade + review results into per-project Markdown and a summary CSV."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from graider.errors import GraiderError
from graider.models import GradeResult, ReviewResult, SetupState

CSV_COLUMNS = [
    "project",
    "url",
    "template",
    "tests_passed",
    "tests_failed",
    "coverage_percent",
    "qlty_issues",
    "qlty_smells",
    "criteria_met",
    "criteria_total",
    "count_emerging",
    "count_developing",
    "count_proficient",
    "count_exemplary",
    "review_model",
]


def load_grades(path: Path) -> list[GradeResult]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else [data]
    return [GradeResult.model_validate(r) for r in rows]


def load_reviews(path: Path) -> list[ReviewResult]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else [data]
    return [ReviewResult.model_validate(r) for r in rows]


def project_urls(state_path: Path | None) -> dict[str, str]:
    if state_path is None or not state_path.exists():
        return {}
    try:
        state = SetupState.model_validate_json(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GraiderError(f"Could not read state file {state_path}: {exc}") from exc
    return {p.name: p.web_url for p in state.projects.values()}


def render_report(grade: GradeResult | None, review: ReviewResult | None, url: str = "") -> str:
    name = (grade.project if grade else None) or (review.project if review else "project")
    lines = [f"# {name}", ""]
    if url:
        lines += [f"Project: {url}", ""]

    if grade is not None:
        cov = "-" if grade.coverage_percent is None else f"{grade.coverage_percent}%"
        lines += [
            "## Metrics",
            "",
            f"- Template: {grade.template}",
            f"- Tests: {grade.tests_passed} passed / {grade.tests_failed} failed",
            f"- Coverage: {cov}",
            f"- qlty: {grade.qlty_issues} issues, {grade.qlty_smells} smells",
        ]
        if grade.errors:
            lines.append(f"- Tool notes: {'; '.join(grade.errors)}")
        lines.append("")

    if review is not None:
        met = sum(v.met for v in review.criteria)
        lines += [
            f"## Review (model {review.model}, cutoff {review.cutoff or 'all'})",
            "",
            f"**{met}/{len(review.criteria)} criteria met.** {review.overall_summary}",
            "",
            "| ID | Criterion | Level | Comment |",
            "| --- | --- | --- | --- |",
        ]
        for v in review.criteria:
            lines.append(f"| {v.id} | {v.title} | {v.level.value} | {v.comment} |")
        lines.append("")
        evidence = [e for v in review.criteria for e in v.evidence]
        if evidence:
            lines += ["### Evidence", "", *[f"- {e}" for e in evidence], ""]

        next_steps = [v for v in review.criteria if v.next_step.strip()]
        if next_steps:
            lines += [
                "### Where to next",
                "",
                *[f"- {v.id}. {v.title}: {v.next_step.strip()}" for v in next_steps],
                "",
            ]

    return "\n".join(lines)


def summary_row(
    grade: GradeResult | None, review: ReviewResult | None, url: str = ""
) -> dict[str, object]:
    name = (grade.project if grade else None) or (review.project if review else "project")
    levels = [v.level.value for v in review.criteria] if review else []
    return {
        "project": name,
        "url": url,
        "template": grade.template if grade else "",
        "tests_passed": grade.tests_passed if grade else "",
        "tests_failed": grade.tests_failed if grade else "",
        "coverage_percent": grade.coverage_percent if grade else "",
        "qlty_issues": grade.qlty_issues if grade else "",
        "qlty_smells": grade.qlty_smells if grade else "",
        "criteria_met": sum(v.met for v in review.criteria) if review else "",
        "criteria_total": len(review.criteria) if review else "",
        # Empty (not 0) when there is no review, so a grade-only project is not
        # mistaken for one reviewed with zero criteria at every level.
        "count_emerging": levels.count("emerging") if review else "",
        "count_developing": levels.count("developing") if review else "",
        "count_proficient": levels.count("proficient") if review else "",
        "count_exemplary": levels.count("exemplary") if review else "",
        "review_model": review.model if review else "",
    }


def write_csv(rows: list[dict[str, object]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
