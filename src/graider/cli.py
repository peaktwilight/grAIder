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
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
    gitlab_url: Optional[str] = typer.Option(
        None,
        "--gitlab-url",
        envvar="GITLAB_URL",
        help="GitLab base URL (default: https://gitlab.com).",
    ),
    token: Optional[str] = typer.Option(
        None,
        "--token",
        envvar="GITLAB_TOKEN",
        help="GitLab personal access token.",
    ),
    config_path: Optional[Path] = typer.Option(
        None,
        "--config",
        help="Path to a config.toml file.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Do not perform any write operations.",
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
    require_token(config)
    print_success(f"setup: not yet implemented (token OK, gitlab_url={config.gitlab_url})")


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


def run() -> None:
    try:
        app()
    except GraiderError as exc:
        print_error(str(exc))
        raise SystemExit(1) from exc
