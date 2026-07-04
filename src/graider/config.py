"""Configuration: layered resolution of GitLab URL and token."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel

from graider.errors import AuthError, ConfigError

DEFAULT_GITLAB_URL = "https://gitlab.com"


class ProjectFile(BaseModel):
    """A discovered project-level graider.toml (instructor course context).

    May carry named `[class.<name>]` sub-sections (E2); `select()` resolves the
    effective context for a chosen class, inheriting top-level defaults.
    """

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
    default_class: str = ""
    classes: dict[str, ProjectFile] = {}

    def resolve_path(self, value: str) -> Path | None:
        """Resolve a relative path value against the config dir."""
        return (self.dir / value) if value else None

    def select(self, class_name: str | None = None) -> ProjectFile:
        """Return the effective context for a class (E2), or self if no classes."""
        if not self.classes:
            return self
        chosen = class_name or self.default_class
        if not chosen and len(self.classes) == 1:
            chosen = next(iter(self.classes))
        if not chosen:
            raise ConfigError(
                f"Multiple classes defined ({sorted(self.classes)}); pass --class <name>."
            )
        if chosen not in self.classes:
            raise ConfigError(f"Unknown class {chosen!r}; choose from {sorted(self.classes)}.")
        cls = self.classes[chosen]
        return ProjectFile(
            dir=self.dir,
            gitlab_url=cls.gitlab_url or self.gitlab_url,
            org=cls.org or self.org,
            roster=cls.roster or self.roster,
            template=cls.template or self.template,
            course=cls.course or self.course or chosen,
            name_prefix=cls.name_prefix or self.name_prefix,
            state=cls.state or self.state,
            brief_url=cls.brief_url or self.brief_url,
            criteria_repo=cls.criteria_repo or self.criteria_repo,
            criteria_path=cls.criteria_path or self.criteria_path,
        )


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

    def _one(section: dict, directory: Path) -> ProjectFile:
        criteria = section.get("criteria") or {}
        return ProjectFile(
            dir=directory,
            gitlab_url=section.get("gitlab_url"),
            org=section.get("org", ""),
            roster=section.get("roster", ""),
            template=section.get("template", ""),
            course=section.get("course", ""),
            name_prefix=section.get("name_prefix", ""),
            state=section.get("state", ""),
            brief_url=section.get("brief_url", ""),
            criteria_repo=criteria.get("repo", ""),
            criteria_path=criteria.get("path", ""),
        )

    project = _one(data, path.parent)
    project.default_class = data.get("default_class", "")
    project.classes = {
        name: _one(section, path.parent) for name, section in (data.get("class") or {}).items()
    }
    return project


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
    class_name: str | None = None,
) -> Config:
    file_data = load_config_file(config_path)
    project_path = find_project_file(project_start)
    project = load_project_file(project_path) if project_path else None
    if project is not None:
        project = project.select(class_name)

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
