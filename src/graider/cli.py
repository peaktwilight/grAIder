"""graider command-line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from graider import __version__
from graider.config import Config, require_token, resolve_config
from graider.console import (
    console,
    print_error,
    print_grade_table,
    print_project_summary,
    print_setup_preview,
    print_success,
)
from graider.errors import GraiderError
from graider.gitlab_client import GitLabClient
from graider.grading.runner import grade_project
from graider.models import MemberState, ProjectState
from graider.names import random_name
from graider.project_config import load_repo_config
from graider.roster import group_students, read_roster
from graider.state import load_state, save_state
from graider.templates import (
    TemplateContext,
    TemplateName,
    render_template,
    write_files,
)

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
def setup(
    ctx: typer.Context,
    roster: Path = typer.Option(
        ...,
        "--roster",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Roster CSV/XLSX (student emails + group numbers).",
    ),
    org: str = typer.Option(
        "",
        "--org",
        help="GitLab group/org full path (e.g. swe/2026). Required unless --dry-run.",
    ),
    template: TemplateName = typer.Option(TemplateName.PYTHON, "--template"),
    course: str = typer.Option("course", "--course"),
    criteria_repo: str = typer.Option("", "--criteria-repo"),
    criteria_path: str = typer.Option("", "--criteria-path"),
    brief_url: str = typer.Option("", "--brief-url"),
    name_prefix: str = typer.Option("", "--name-prefix"),
    state_path: Path = typer.Option(Path("graider.lock.json"), "--state"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Create a GitLab project per group and invite members."""
    config = _config(ctx)
    dry_run = dry_run or config.dry_run

    groups = group_students(read_roster(roster))
    state = load_state(state_path)

    # --- offline preview ---------------------------------------------------
    if dry_run:
        taken = {p.name for p in state.projects.values()}
        rows = []
        for group in groups:
            if group.number in state.projects:
                name = state.projects[group.number].name
            else:
                name = random_name(taken, prefix=name_prefix)
                taken.add(name)
            rows.append((group.number, name, group.members))
        print_setup_preview(rows)
        print_success(f"{len(groups)} groups (dry run, GitLab untouched).")
        return

    # --- real run ----------------------------------------------------------
    if not org:
        raise GraiderError("--org is required (the GitLab group to create projects in).")
    token = require_token(config)

    client = GitLabClient(config.gitlab_url, token)
    client.authenticate()
    namespace_id = client.get_namespace_id(org)
    state.gitlab_url, state.org = config.gitlab_url, org

    taken = client.list_group_project_paths(org) | {p.name for p in state.projects.values()}

    for group in groups:
        if group.number in state.projects:
            _reconcile_members(client, state.projects[group.number], group)
        else:
            name = random_name(taken, prefix=name_prefix)
            taken.add(name)
            ref = client.create_project(name, namespace_id)
            assert ref is not None  # not dry-run here
            context = TemplateContext(
                project_name=name,
                course=course,
                criteria_repo=criteria_repo,
                criteria_path=criteria_path,
                brief_url=brief_url,
            )
            client.commit_files(ref.id, render_template(template.value, context))
            client.protect_branch(ref.id, "main")
            members = [
                MemberState(**client.invite_member(ref.id, s.email).model_dump())
                for s in group.members
            ]
            state.projects[group.number] = ProjectState(
                group_number=group.number,
                name=name,
                project_id=ref.id,
                web_url=ref.web_url,
                path_with_namespace=ref.path_with_namespace,
                template=template.value,
                members=members,
            )
        save_state(state_path, state)  # incremental save = resumable

    print_project_summary(state)
    print_success(f"Set up {len(state.projects)} projects → {state_path}")


def _reconcile_members(client, project, group) -> None:
    """Invite roster members not already successfully added (idempotent re-run)."""
    from graider.models import InviteStatus

    recorded = {m.email: m for m in project.members}
    for student in group.members:
        current = recorded.get(student.email)
        if current and current.status in (InviteStatus.INVITED, InviteStatus.ALREADY_MEMBER):
            continue
        result = client.invite_member(project.project_id, student.email)
        recorded[student.email] = MemberState(**result.model_dump())
    project.members = list(recorded.values())


@app.command()
def grade(
    ctx: typer.Context,
    repo: Path = typer.Option(Path("."), "--repo", help="Repo to grade (student mode)."),
    workspace: Optional[Path] = typer.Option(
        None,
        "--workspace",
        help="Grade every subdir with a .graider.yml (teacher mode).",
    ),
    results: Path = typer.Option(Path("grade-results.json"), "--results"),
) -> None:
    """Grade a repo (or a workspace of repos) with qlty + tests + coverage."""
    if workspace is not None:
        targets = sorted(d for d in workspace.iterdir() if (d / ".graider.yml").exists())
        if not targets:
            raise GraiderError(f"No repos with a .graider.yml under {workspace}")
    else:
        if load_repo_config(repo) is None:
            raise GraiderError(f"No .graider.yml in {repo}; pass --workspace for teacher mode.")
        targets = [repo]

    graded = [grade_project(t) for t in targets]
    print_grade_table(graded)
    results.write_text(
        json.dumps([g.model_dump() for g in graded], indent=2) + "\n", encoding="utf-8"
    )
    print_success(f"Graded {len(graded)} project(s) → {results}")


@app.command()
def review(ctx: typer.Context) -> None:
    """Agentic AI grading against course criteria. (stub)"""
    console.print("review: not yet implemented")


@app.command()
def report(ctx: typer.Context) -> None:
    """Aggregate and export results. (stub)"""
    console.print("report: not yet implemented")


template_app = typer.Typer(help="Inspect and render starter templates.")
app.add_typer(template_app, name="template")


@template_app.command("list")
def template_list() -> None:
    """List the available starter templates."""
    for name in TemplateName:
        console.print(name.value)


@template_app.command("render")
def template_render(
    template: TemplateName = typer.Option(..., "--template", help="Which starter."),
    out: Path = typer.Option(..., "--out", help="Output directory."),
    project_name: str = typer.Option("project", "--name"),
    course: str = typer.Option("course", "--course"),
    criteria_repo: str = typer.Option("", "--criteria-repo"),
    criteria_path: str = typer.Option("", "--criteria-path"),
    brief_url: str = typer.Option("", "--brief-url"),
) -> None:
    """Render a starter template into a local directory (offline)."""
    context = TemplateContext(
        project_name=project_name,
        course=course,
        criteria_repo=criteria_repo,
        criteria_path=criteria_path,
        brief_url=brief_url,
    )
    rendered = render_template(template.value, context)
    write_files(rendered, out)
    print_success(f"Rendered {len(rendered)} files to {out}")


def run() -> None:
    try:
        app()
    except GraiderError as exc:
        print_error(str(exc))
        raise SystemExit(1) from exc
