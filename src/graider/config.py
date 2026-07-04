"""Configuration: layered resolution of GitLab URL and token."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel

from graider.errors import AuthError, ConfigError

DEFAULT_GITLAB_URL = "https://gitlab.com"


class Config(BaseModel):
    """Resolved runtime configuration."""

    gitlab_url: str
    token: str | None = None
    dry_run: bool = False


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
) -> Config:
    file_data = load_config_file(config_path)
    resolved_url = gitlab_url or file_data.get("gitlab_url") or DEFAULT_GITLAB_URL
    resolved_token = token or file_data.get("token")
    return Config(gitlab_url=resolved_url, token=resolved_token, dry_run=dry_run)


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
