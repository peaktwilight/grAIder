"""Content-hash cache of review results, to skip re-running the model.

The key hashes the exact model input (model id + system + user prompt), so a
cached result is reused only when nothing that affects the output changed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from graider.models import ReviewResult


def cache_key(model: str, system: str, user_prompt: str) -> str:
    h = hashlib.sha256()
    for part in (model, system, user_prompt):
        h.update(part.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


class ReviewCache:
    """A small JSON-file cache mapping cache_key -> ReviewResult."""

    def __init__(self, path: Path, entries: dict[str, dict]) -> None:
        self.path = path
        self._entries = entries
        self.last_hit = False

    @classmethod
    def load(cls, path: Path) -> ReviewCache:
        entries: dict[str, dict] = {}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    entries = loaded
            except (json.JSONDecodeError, OSError):
                entries = {}
        return cls(path, entries)

    def get(self, key: str) -> ReviewResult | None:
        raw = self._entries.get(key)
        if raw is None:
            return None
        try:
            return ReviewResult.model_validate(raw)
        except ValidationError:
            return None

    def put(self, key: str, result: ReviewResult) -> None:
        self._entries[key] = result.model_dump()
        self.path.write_text(json.dumps(self._entries, indent=2) + "\n", encoding="utf-8")
