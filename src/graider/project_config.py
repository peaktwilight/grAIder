"""Read a student repo's .graider.yml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from graider.errors import GraiderError


class RepoConfig(BaseModel):
    course: str = ""
    template: str
    criteria_repo: str = ""
    criteria_path: str = ""


def load_repo_config(repo_dir: Path) -> RepoConfig | None:
    """Return the repo's .graider.yml as a RepoConfig, or None if absent."""
    path = repo_dir / ".graider.yml"
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise GraiderError(f"Invalid .graider.yml in {repo_dir}: {exc}") from exc
    criteria = data.get("criteria") or {}
    template = data.get("template")
    if not template:
        raise GraiderError(f".graider.yml in {repo_dir} is missing `template`")
    return RepoConfig(
        course=data.get("course") or "",
        template=template,
        criteria_repo=criteria.get("repo") or "",
        criteria_path=criteria.get("path") or "",
    )
