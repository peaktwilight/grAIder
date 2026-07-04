"""Read/write the graider.lock.json setup state file."""

from __future__ import annotations

from pathlib import Path

from graider.errors import GraiderError
from graider.models import SetupState


def load_state(path: Path) -> SetupState:
    """Load the state file, or return an empty state if it does not exist."""
    if not path.exists():
        return SetupState()
    try:
        return SetupState.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GraiderError(f"Could not read state file {path}: {exc}") from exc


def save_state(path: Path, state: SetupState) -> None:
    path.write_text(state.model_dump_json(indent=2) + "\n", encoding="utf-8")
