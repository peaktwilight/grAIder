"""Configuration: layered resolution of GitLab URL and token."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel

from graider.errors import AuthError, ConfigError

DEFAULT_GITLAB_URL = "https://gitlab.com"


class ProjectFile(BaseModel):
    """A discovered project-level graider.toml (instructor course context)."""

    dir: Path  # directory containing graider.toml
    gitlab_url: str | None = None
    org: str = ""
    roster: str = ""
    template: str = ""
    course: str = ""
    name_prefix: str = ""
    state: str = ""
    brief_url: str = ""
    criteria_repo: str = ""
    criteria_path: str = ""

    def resolve_path(self, value: str) -> Path | None:
        """Resolve a relative path value against the config dir."""
        return (self.dir / value) if value else None


class Config(BaseModel):
    """Resolved runtime configuration."""

    gitlab_url: str
    token: str | None = None
    dry_run: bool = False
    project: ProjectFile | None = None


def find_project_file(start: Path | None = None) -> Path | None:
    """Walk up from `start` (default cwd) to find a graider.toml."""
    current = (start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        candidate = directory / "graider.toml"
        if candidate.exists():
            return candidate
    return None


def load_project_file(path: Path) -> ProjectFile:
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"Could not read {path}: {exc}") from exc
    criteria = data.get("criteria") or {}
    return ProjectFile(
        dir=path.parent,
        gitlab_url=data.get("gitlab_url"),
        org=data.get("org", ""),
        roster=data.get("roster", ""),
        template=data.get("template", ""),
        course=data.get("course", ""),
        name_prefix=data.get("name_prefix", ""),
        state=data.get("state", ""),
        brief_url=data.get("brief_url", ""),
        criteria_repo=criteria.get("repo", ""),
        criteria_path=criteria.get("path", ""),
    )


def default_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "graider" / "config.toml"


def load_config_file(config_path: Path | None) -> dict:
    """Return the parsed config file, or {} if it does not exist."""
    path = config_path or default_config_path()
    if not path.exists():
        return {}
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"Could not read config file {path}: {exc}") from exc


def resolve_config(
    *,
    token: str | None,
    gitlab_url: str | None,
    config_path: Path | None,
    dry_run: bool = False,
    project_start: Path | None = None,
) -> Config:
    file_data = load_config_file(config_path)
    project_path = find_project_file(project_start)
    project = load_project_file(project_path) if project_path else None

    resolved_url = (
        gitlab_url
        or (project.gitlab_url if project else None)
        or file_data.get("gitlab_url")
        or DEFAULT_GITLAB_URL
    )
    resolved_token = token or file_data.get("token")
    return Config(gitlab_url=resolved_url, token=resolved_token, dry_run=dry_run, project=project)


def token_creation_url(gitlab_url: str) -> str:
    base = gitlab_url.rstrip("/")
    return f"{base}/-/user_settings/personal_access_tokens"


def require_token(config: Config) -> str:
    """Return the token, or raise AuthError with guidance if it is missing."""
    if config.token:
        return config.token
    url = token_creation_url(config.gitlab_url)
    raise AuthError(
        "No GitLab token found.\n\n"
        "Create a personal access token (scope: api) here:\n"
        f"    {url}\n\n"
        "Then provide it with one of:\n"
        "    • --token <token>\n"
        "    • export GITLAB_TOKEN=<token>\n"
        '    • add  token = "<token>"  to ~/.config/graider/config.toml'
    )
