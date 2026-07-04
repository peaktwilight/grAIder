"""Load grading criteria (Markdown/AsciiDoc) with ordered items + staggered cutoff."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import yaml

from graider.errors import GraiderError
from graider.models import Criteria, CriteriaItem

_MARKERS = {".md": "## ", ".markdown": "## ", ".adoc": "== ", ".asciidoc": "== "}
_NUM_PREFIX = re.compile(r"^\s*(\d+)[.)]\s*")


def parse_criteria(text: str, marker: str = "## ") -> Criteria:
    lines = text.splitlines()
    brief_lines: list[str] = []
    items: list[CriteriaItem] = []
    current: CriteriaItem | None = None
    body: list[str] = []

    def _flush() -> None:
        if current is not None:
            current.body = "\n".join(body).strip()
            items.append(current)

    for line in lines:
        if line.startswith(marker):
            _flush()
            body = []
            heading = line[len(marker) :].strip()
            match = _NUM_PREFIX.match(heading)
            if match:
                item_id = match.group(1)
                title = heading[match.end() :].strip()
            else:
                title = heading
                item_id = _slug(title)
            current = CriteriaItem(id=item_id, title=title, order=len(items) + 1)
        elif current is None:
            brief_lines.append(line)
        else:
            body.append(line)
    _flush()

    brief = "\n".join(brief_lines).strip()
    brief = re.sub(r"^#+\s*", "", brief)  # drop a leading markdown/adoc title line marker
    return Criteria(brief=brief, items=items)


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def load_criteria_dir(criteria_dir: Path) -> Criteria:
    """Parse the single criteria document found in a directory."""
    docs = [
        p for p in sorted(criteria_dir.iterdir()) if p.suffix.lower() in _MARKERS and p.is_file()
    ]
    if not docs:
        raise GraiderError(f"No criteria document (.md/.adoc) found in {criteria_dir}")
    doc = docs[0]
    return parse_criteria(doc.read_text(encoding="utf-8"), _MARKERS[doc.suffix.lower()])


def released_cutoff(criteria_dir: Path) -> str | int | None:
    """Read `released_up_to` from graider-criteria.yml, if present."""
    path = criteria_dir / "graider-criteria.yml"
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("released_up_to")


def split_by_cutoff(
    items: list[CriteriaItem], cutoff: str | int | None
) -> tuple[list[CriteriaItem], list[CriteriaItem]]:
    """Return (in_scope, out_of_scope). cutoff is a 1-based position or an item id."""
    if cutoff is None or cutoff == "":
        return list(items), []
    index = _cutoff_index(items, cutoff)
    return items[:index], items[index:]


def _cutoff_index(items: list[CriteriaItem], cutoff: str | int) -> int:
    text = str(cutoff)
    if text.isdigit():
        return min(int(text), len(items))
    for i, item in enumerate(items):
        if item.id == text:
            return i + 1
    raise GraiderError(f"--up-to {cutoff!r} matches no criteria item id")


def fetch_criteria_repo(repo_url: str, path: str = "", ref: str = "main") -> Path:
    """Shallow-clone a criteria repo and return the local path to `path` inside it.

    Best-effort: relies on git + whatever auth the environment already has for
    repo_url. Tests use local dirs instead.
    """
    tmp = Path(tempfile.mkdtemp(prefix="graider-criteria-"))
    proc = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", ref, repo_url, str(tmp)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise GraiderError(f"Could not clone criteria repo {repo_url}: {proc.stderr.strip()}")
    return tmp / path if path else tmp
