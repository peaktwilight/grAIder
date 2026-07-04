"""Render a ReviewResult into GitLab feedback markdown (shared by MR + issue)."""

from __future__ import annotations

from graider.models import ReviewResult

# Hidden marker so re-runs update the same note/issue instead of duplicating.
REVIEW_MARKER = "<!-- graider:review -->"


def render_feedback(review: ReviewResult) -> str:
    met = sum(v.met for v in review.criteria)
    total = len(review.criteria)
    lines = [
        REVIEW_MARKER,
        f"## grAIder review — {met}/{total} criteria met (cutoff: {review.cutoff or 'all'})",
        "",
        review.overall_summary,
        "",
    ]
    for v in review.criteria:
        box = "x" if v.met else " "
        tail = f" — {v.comment}" if v.comment and not v.met else ""
        lines.append(f"- [{box}] {v.id}. {v.title}{tail}")
    return "\n".join(lines)


def issue_title(review: ReviewResult) -> str:
    return f"grAIder feedback — {review.cutoff or 'all'} criteria"
