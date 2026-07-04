# Milestone 1 — Detailed Implementation Plan

**Goal:** a working `graider` CLI skeleton with subcommand stubs, global options,
layered config, and GitLab token resolution — including the "no token" UX that
prints the exact URL to create one.

This document is prescriptive. Follow the steps in order. Where full code is
given, you may copy it verbatim. Do not add features from later milestones.

**Definition of done (verify all at the end):**

- `uv run graider --version` prints the version and exits 0.
- `uv run graider --help` lists `setup`, `grade`, `review`, `report`.
- `uv run graider setup` with **no token** prints the token-creation URL and
  exits with code 1.
- `uv run graider setup` **with** a token (env or flag) prints a placeholder
  success line and exits 0.
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`, and
  `uv run pytest` all pass.

---

## Step 1 — Add dependencies

Edit `pyproject.toml`. Add a `[project.dependencies]` list (runtime deps) and
keep the existing dev group.

Replace the `dependencies = []` line under `[project]` with:

```toml
dependencies = [
    "typer>=0.12",
    "rich>=13.7",
    "pydantic>=2.7",
]
```

> Only these three are needed for Milestone 1. `python-gitlab`, `openpyxl`, and
> `pyyaml` are added in their own milestones — do not add them now.

Change the console-script entry point. Under `[project.scripts]` replace:

```toml
graider = "graider.main:main"
```

with:

```toml
graider = "graider.cli:app"
```

Then run:

```sh
uv sync
```

Expected: typer, rich, pydantic and their deps install without error.

---

## Step 2 — Target file layout

After this milestone the package looks like:

```
src/graider/
├── __init__.py      # __version__
├── cli.py           # Typer app: callback + 4 subcommand stubs
├── config.py        # Config model, resolution, token URL, require_token
├── console.py       # shared Rich consoles + print helpers
└── errors.py        # exception types
tests/
├── test_config.py
└── test_cli.py
```

Delete `src/graider/main.py` (its `greet`/`main` were placeholder). Update the
existing `tests/test_main.py`: delete it (a new `test_cli.py` replaces it).

```sh
rm src/graider/main.py tests/test_main.py
```

---

## Step 3 — `src/graider/__init__.py`

Read the installed package version so it never drifts from `pyproject.toml`.

```python
"""graider package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("graider")
except PackageNotFoundError:  # not installed (e.g. running from a raw checkout)
    __version__ = "0.0.0"

__all__ = ["__version__"]
```

---

## Step 4 — `src/graider/errors.py`

All user-facing errors inherit from `GraiderError`. The CLI catches this base
type and prints `.args[0]` as a clean message (no traceback).

```python
"""Exception types. Any GraiderError message is safe to show the user."""


class GraiderError(Exception):
    """Base class for expected, user-facing errors."""


class ConfigError(GraiderError):
    """Configuration is missing or malformed."""


class AuthError(GraiderError):
    """A GitLab token is required but was not found."""
```

---

## Step 5 — `src/graider/console.py`

Shared Rich consoles and small print helpers. Normal output → stdout; errors and
warnings → stderr.

```python
"""Shared Rich consoles and output helpers."""

from rich.console import Console

console = Console()
err_console = Console(stderr=True)


def print_error(message: str) -> None:
    err_console.print(f"[bold red]✗[/] {message}")


def print_warning(message: str) -> None:
    err_console.print(f"[bold yellow]![/] {message}")


def print_success(message: str) -> None:
    console.print(f"[bold green]✓[/] {message}")
```

---

## Step 6 — `src/graider/config.py`

This is the core of the milestone. Keep it free of any Typer imports so it is
unit-testable on its own.

### Behavior

- **Default GitLab URL:** `https://gitlab.com`.
- **Config file location:** `$XDG_CONFIG_HOME/graider/config.toml`, falling back
  to `~/.config/graider/config.toml`. Parsed with stdlib `tomllib`.
  Recognized keys: `gitlab_url` (str), `token` (str). Missing file → `{}`.
- **Resolution precedence** (first non-empty wins):
  - `gitlab_url`: explicit arg → config file → default.
  - `token`: explicit arg → config file → `None`.
  - (The environment variable layer is handled by Typer in `cli.py` via
    `envvar=`, so it arrives here already folded into the explicit arg.)
- **Token-creation URL:** `{gitlab_url}/-/user_settings/personal_access_tokens`
  (trailing slashes on the base URL are stripped first).
- **`require_token`** raises `AuthError` with a multi-line message containing the
  URL and the three ways to supply a token.

### Full code

```python
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
```

---

## Step 7 — `src/graider/cli.py`

The Typer app. The `@app.callback()` collects global options, resolves config,
and stores it on `ctx.obj`. Each subcommand reads `ctx.obj`.

Key requirements:
- `--version` is an eager option that prints and exits before anything else.
- `--gitlab-url` default is `None` (so the config file can supply it); env var
  `GITLAB_URL`.
- `--token` default `None`; env var `GITLAB_TOKEN`.
- `--config` lets tests point at a temp config file.
- `--dry-run` is stored for later milestones.
- A top-level `try/except GraiderError` wrapper prints the message via
  `print_error` and exits 1 — no traceback for expected errors.

### Full code

```python
"""graider command-line interface."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from graider import __version__
from graider.config import Config, require_token, resolve_config
from graider.console import console, print_error, print_success
from graider.errors import GraiderError

app = typer.Typer(
    name="graider",
    help="Set up and grade GitLab coursework projects.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        console.print(__version__)
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(
        None, "--version", callback=_version_callback, is_eager=True,
        help="Show the version and exit.",
    ),
    gitlab_url: Optional[str] = typer.Option(
        None, "--gitlab-url", envvar="GITLAB_URL",
        help="GitLab base URL (default: https://gitlab.com).",
    ),
    token: Optional[str] = typer.Option(
        None, "--token", envvar="GITLAB_TOKEN",
        help="GitLab personal access token.",
    ),
    config_path: Optional[Path] = typer.Option(
        None, "--config", help="Path to a config.toml file.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Do not perform any write operations.",
    ),
) -> None:
    """Resolve global config and stash it on the context."""
    ctx.obj = resolve_config(
        token=token, gitlab_url=gitlab_url, config_path=config_path, dry_run=dry_run
    )


def _config(ctx: typer.Context) -> Config:
    return ctx.obj  # type: ignore[return-value]


@app.command()
def setup(ctx: typer.Context) -> None:
    """Create GitLab projects from a roster. (stub)"""
    config = _config(ctx)
    try:
        require_token(config)
    except GraiderError as exc:
        print_error(str(exc))
        raise typer.Exit(code=1) from exc
    print_success(
        f"setup: not yet implemented (token OK, gitlab_url={config.gitlab_url})"
    )


@app.command()
def grade(ctx: typer.Context) -> None:
    """Run qlty + tests + coverage over projects. (stub)"""
    console.print("grade: not yet implemented")


@app.command()
def review(ctx: typer.Context) -> None:
    """Agentic AI grading against course criteria. (stub)"""
    console.print("review: not yet implemented")


@app.command()
def report(ctx: typer.Context) -> None:
    """Aggregate and export results. (stub)"""
    console.print("report: not yet implemented")
```

> Use `Optional[X]` (imported from `typing`), not `X | None`, in the Typer
> option signatures — some Typer/Click versions choke on the `|` syntax when
> introspecting defaults. Everywhere else, `X | None` is fine.

---

## Step 8 — Tests

Use Typer's `CliRunner`. Isolate config by always passing `--config` at a path
that does not exist (so the file layer is empty) unless a test writes one.

### `tests/test_config.py`

```python
from pathlib import Path

import pytest

from graider.config import (
    DEFAULT_GITLAB_URL,
    require_token,
    resolve_config,
    token_creation_url,
)
from graider.errors import AuthError


def _missing(tmp_path: Path) -> Path:
    return tmp_path / "nope.toml"


def test_token_from_arg(tmp_path):
    cfg = resolve_config(token="glpat-x", gitlab_url=None, config_path=_missing(tmp_path))
    assert cfg.token == "glpat-x"


def test_token_from_file(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text('token = "glpat-file"\n')
    cfg = resolve_config(token=None, gitlab_url=None, config_path=f)
    assert cfg.token == "glpat-file"


def test_arg_beats_file(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text('token = "glpat-file"\n')
    cfg = resolve_config(token="glpat-arg", gitlab_url=None, config_path=f)
    assert cfg.token == "glpat-arg"


def test_no_token_is_none(tmp_path):
    cfg = resolve_config(token=None, gitlab_url=None, config_path=_missing(tmp_path))
    assert cfg.token is None


def test_gitlab_url_default(tmp_path):
    cfg = resolve_config(token=None, gitlab_url=None, config_path=_missing(tmp_path))
    assert cfg.gitlab_url == DEFAULT_GITLAB_URL


def test_gitlab_url_from_file(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text('gitlab_url = "https://git.uni.edu"\n')
    cfg = resolve_config(token=None, gitlab_url=None, config_path=f)
    assert cfg.gitlab_url == "https://git.uni.edu"


def test_gitlab_url_arg_beats_file(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text('gitlab_url = "https://git.uni.edu"\n')
    cfg = resolve_config(
        token=None, gitlab_url="https://gitlab.com", config_path=f
    )
    assert cfg.gitlab_url == "https://gitlab.com"


def test_token_url_default():
    assert token_creation_url("https://gitlab.com") == (
        "https://gitlab.com/-/user_settings/personal_access_tokens"
    )


def test_token_url_self_hosted_strips_slash():
    assert token_creation_url("https://git.uni.edu/") == (
        "https://git.uni.edu/-/user_settings/personal_access_tokens"
    )


def test_require_token_ok(tmp_path):
    cfg = resolve_config(token="glpat-x", gitlab_url=None, config_path=_missing(tmp_path))
    assert require_token(cfg) == "glpat-x"


def test_require_token_raises_with_url(tmp_path):
    cfg = resolve_config(
        token=None, gitlab_url="https://git.uni.edu", config_path=_missing(tmp_path)
    )
    with pytest.raises(AuthError) as excinfo:
        require_token(cfg)
    assert "https://git.uni.edu/-/user_settings/personal_access_tokens" in str(
        excinfo.value
    )
```

### `tests/test_cli.py`

```python
from typer.testing import CliRunner

from graider import __version__
from graider.cli import app

runner = CliRunner()


def _no_config(tmp_path):
    # Point --config at a nonexistent file so no real ~/.config leaks in.
    return ["--config", str(tmp_path / "nope.toml")]


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_help_lists_subcommands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("setup", "grade", "review", "report"):
        assert name in result.stdout


def test_setup_without_token_shows_url(tmp_path):
    result = runner.invoke(app, [*_no_config(tmp_path), "setup"], env={})
    assert result.exit_code == 1
    assert "/-/user_settings/personal_access_tokens" in result.output


def test_setup_with_token_env(tmp_path):
    result = runner.invoke(
        app, [*_no_config(tmp_path), "setup"], env={"GITLAB_TOKEN": "glpat-x"}
    )
    assert result.exit_code == 0
    assert "not yet implemented" in result.output


def test_setup_self_hosted_url(tmp_path):
    result = runner.invoke(
        app,
        [*_no_config(tmp_path), "--gitlab-url", "https://git.uni.edu", "setup"],
        env={},
    )
    assert result.exit_code == 1
    assert "https://git.uni.edu/-/user_settings/personal_access_tokens" in result.output
```

> Notes for the implementer:
> - `CliRunner(mix_stderr=...)` differs across Click versions. If `result.stdout`
>   does not contain stderr text, assert against `result.output` (as above),
>   which includes both streams by default in current Click.
> - Passing `env={}` to `invoke` does **not** clear the real environment. If your
>   machine actually exports `GITLAB_TOKEN`, the "without token" tests will fail.
>   In that case use `monkeypatch.delenv("GITLAB_TOKEN", raising=False)` in the
>   test before invoking.

---

## Step 9 — Verify

Run each and confirm the expected result:

```sh
uv sync
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest -q

uv run graider --version          # prints version, exit 0
uv run graider --help             # lists setup/grade/review/report
env -u GITLAB_TOKEN uv run graider setup   # prints token URL, exit 1
GITLAB_TOKEN=glpat-x uv run graider setup  # "setup: not yet implemented", exit 0
```

If `ruff format --check` fails, run `uv run ruff format .` and re-check.

---

## Notes for the next milestone

- `Config` already carries `dry_run`; Milestone 3+ will read it before any write.
- `resolve_config` is the single choke point for config — Milestone 2's roster
  path and Milestone 7's criteria settings should flow through the same pattern
  (explicit arg → file → default), not ad-hoc `os.environ` reads.
- Keep `config.py` Typer-free so it stays unit-testable.
```
