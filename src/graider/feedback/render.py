"""Render a ReviewResult into GitLab feedback markdown (shared by MR + issue)."""

from __future__ import annotations

from graider.models import ReviewResult

# Hidden marker so re-runs update the same note/issue instead of duplicating.
REVIEW_MARKER = "<!-- graider:review -->"


def render_feedback(review: ReviewResult) -> str:
    if review.formative:
        header = "## grAIder self-check (formative — not a grade)"
    else:
        met = sum(v.met for v in review.criteria)
        total = len(review.criteria)
        header = (
            f"## grAIder review — {met}/{total} criteria met (cutoff: {review.cutoff or 'all'})"
        )
    lines = [
        REVIEW_MARKER,
        header,
        "",
        review.overall_summary,
        "",
        "### Where am I going? (Goals for this milestone)",
        "",
    ]
    for v in review.criteria:
        lines.append(f"- {v.id}. {v.title}")
    lines += ["", "### How am I going? (What your work shows)", ""]
    for v in review.criteria:
        tail = f" — {v.comment}" if v.comment else ""
        lines.append(f"- {v.id}. {v.title}: **{v.level.value}**{tail}")
    next_steps = [v for v in review.criteria if v.next_step.strip()]
    if next_steps:
        lines += ["", "### Where to next?", ""]
        for v in next_steps:
            lines.append(f"- {v.id}. {v.title}: {v.next_step.strip()}")
    if review.progress:
        symbols = {"improved": "↑", "regressed": "↓", "unchanged": "→", "new": "＋"}
        lines += ["", "### Progress since last review", ""]
        for p in review.progress:
            arrow = symbols.get(p.change, "•")
            span = f" ({p.from_level} → {p.to_level})" if p.from_level else f" ({p.to_level})"
            lines.append(f"- {arrow} {p.id}. {p.title}: {p.change}{span}")
    return "\n".join(lines)


def issue_title(review: ReviewResult) -> str:
    return f"grAIder feedback — {review.cutoff or 'all'} criteria"
