"""Neutral git-history signals for a repo (cadence, contribution, code drops).

These inform teacher triage and viva questions; they are NOT evidence of
misconduct and must never drive an automatic penalty.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import date
from pathlib import Path

from graider.models import HistoryMetrics

_SEP = "\x1f"  # unit separator: safe delimiter for the log format


def analyze_history(repo_dir: Path, since: str = "") -> HistoryMetrics | None:
    """Return git-history signals for repo_dir, or None if git/history is absent."""
    if not shutil.which("git"):
        return None
    args = [
        "git",
        "-C",
        str(repo_dir),
        "log",
        "--no-merges",
        "--numstat",
        "--date=short",
        f"--pretty=format:C{_SEP}%ae{_SEP}%ad",
    ]
    if since:
        args.append(f"--since={since}")
    try:
        proc = subprocess.run(args, capture_output=True, text=True)
    except FileNotFoundError:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return _parse_log(proc.stdout)


def _parse_log(text: str) -> HistoryMetrics:
    """Parse `git log --numstat` output (see analyze_history) into HistoryMetrics."""
    commits = 0
    authors: dict[str, int] = {}
    days: set[str] = set()
    largest = 0
    current = 0

    for line in text.splitlines():
        if line.startswith("C" + _SEP):
            largest = max(largest, current)
            current = 0
            _, email, day = line.split(_SEP)
            commits += 1
            authors[email] = authors.get(email, 0) + 1
            days.add(day)
        elif line.strip():
            cols = line.split("\t")
            if len(cols) >= 2:
                current += sum(int(c) for c in cols[:2] if c.isdigit())
    largest = max(largest, current)

    span = 0
    if days:
        span = (date.fromisoformat(max(days)) - date.fromisoformat(min(days))).days
    return HistoryMetrics(
        commits=commits,
        commit_days=len(days),
        span_days=span,
        authors=authors,
        largest_commit_lines=largest,
    )
