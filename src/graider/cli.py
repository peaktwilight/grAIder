"""graider command-line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from graider import __version__
from graider.authoring.criteria import DEFAULT_MODEL as CRITERIA_MODEL
from graider.authoring.criteria import (
    check_criteria_dir,
    draft_criteria,
    write_criteria_dir,
)
from graider.config import Config, require_token, resolve_config
from graider.console import (
    console,
    print_check_report,
    print_criteria_scope,
    print_error,
    print_grade_table,
    print_project_summary,
    print_report_summary,
    print_review,
    print_setup_preview,
    print_success,
)
from graider.criteria import (
    fetch_criteria_repo,
    load_criteria_dir,
    released_cutoff,
    split_by_cutoff,
)
from graider.errors import GraiderError
from graider.gitlab_client import GitLabClient
from graider.grading.runner import grade_project
from graider.models import MemberState, ProjectState
from graider.names import random_name
from graider.project_config import load_repo_config
from graider.report.build import (
    load_grades,
    load_reviews,
    project_urls,
    render_report,
    summary_row,
    write_csv,
)
from graider.review.agent import DEFAULT_MODEL, head_sha, review_project, select_backend
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
    class_name: Optional[str] = typer.Option(
        None,
        "--class",
        help="Select a class from graider.toml [class.<name>] sections.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Do not perform any write operations.",
    ),
) -> None:
    """Resolve global config and stash it on the context."""
    ctx.obj = resolve_config(
        token=token,
        gitlab_url=gitlab_url,
        config_path=config_path,
        dry_run=dry_run,
        class_name=class_name,
    )


def _config(ctx: typer.Context) -> Config:
    return ctx.obj  # type: ignore[return-value]


@app.command()
def setup(
    ctx: typer.Context,
    roster: Optional[Path] = typer.Option(
        None,
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
    template: Optional[TemplateName] = typer.Option(None, "--template"),
    course: str = typer.Option("", "--course"),
    criteria_repo: str = typer.Option("", "--criteria-repo"),
    criteria_path: str = typer.Option("", "--criteria-path"),
    brief_url: str = typer.Option("", "--brief-url"),
    name_prefix: str = typer.Option("", "--name-prefix"),
    state_path: Optional[Path] = typer.Option(None, "--state"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Create a GitLab project per group and invite members."""
    config = _config(ctx)
    pf = config.project
    dry_run = dry_run or config.dry_run

    # Fall back to graider.toml (E1) for any flag not given on the CLI.
    org = org or (pf.org if pf else "")
    course = course or (pf.course if pf else "") or "course"
    criteria_repo = criteria_repo or (pf.criteria_repo if pf else "")
    criteria_path = criteria_path or (pf.criteria_path if pf else "")
    brief_url = brief_url or (pf.brief_url if pf else "")
    name_prefix = name_prefix or (pf.name_prefix if pf else "")
    template = template or (
        TemplateName(pf.template) if pf and pf.template else TemplateName.PYTHON
    )
    if roster is None and pf and pf.roster:
        roster = pf.resolve_path(pf.roster)
    if roster is None:
        raise GraiderError("No roster: pass --roster or set roster in graider.toml")
    if state_path is None:
        state_path = (pf.resolve_path(pf.state) if pf and pf.state else None) or Path(
            "graider.lock.json"
        )

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
def review(
    ctx: typer.Context,
    repo: Path = typer.Option(Path("."), "--repo"),
    criteria_dir: Optional[Path] = typer.Option(None, "--criteria-dir"),
    criteria_repo: str = typer.Option("", "--criteria-repo"),
    criteria_path: str = typer.Option("", "--criteria-path"),
    up_to: Optional[str] = typer.Option(None, "--up-to", help="Position or item id."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    model: str = typer.Option(DEFAULT_MODEL, "--model", help="Claude model id."),
    force: bool = typer.Option(False, "--force", help="Re-review even if HEAD is unchanged."),
    results: Path = typer.Option(Path("review-results.json"), "--results"),
    backend: str = typer.Option(
        "auto", "--backend", help="Model backend: auto | api | claude-code."
    ),
) -> None:
    """Evaluate a repo against the (staggered) criteria. (loading + preview)"""
    config = _config(ctx)
    source = _resolve_criteria_dir(repo, criteria_dir, criteria_repo, criteria_path)
    criteria = load_criteria_dir(source)

    cutoff: str | int | None = up_to if up_to is not None else released_cutoff(source)
    in_scope, out_scope = split_by_cutoff(criteria.items, cutoff)

    if dry_run or config.dry_run:
        print_criteria_scope(in_scope, out_scope)
        print_success(f"{len(in_scope)} of {len(criteria.items)} criteria in scope (dry run).")
        return

    results_path = results
    if not force and results_path.exists():
        prior = json.loads(results_path.read_text(encoding="utf-8"))
        if prior.get("head_sha") and prior["head_sha"] == head_sha(repo):
            console.print("Repo unchanged since last review; use --force to re-run.")
            return

    result = review_project(
        repo,
        criteria.brief,
        in_scope,
        cutoff=str(cutoff) if cutoff is not None else "",
        model=model,
        backend=select_backend(backend),
    )
    print_review(result)
    results_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print_success(f"Reviewed {len(in_scope)} criteria → {results_path}")


def _resolve_criteria_dir(repo, criteria_dir, criteria_repo, criteria_path) -> Path:
    if criteria_dir is not None:
        return criteria_dir
    if criteria_repo:
        return fetch_criteria_repo(criteria_repo, criteria_path)
    cfg = load_repo_config(repo)  # student mode: .graider.yml
    if cfg is not None and cfg.criteria_repo:
        return fetch_criteria_repo(cfg.criteria_repo, cfg.criteria_path)
    raise GraiderError(
        "No criteria source: pass --criteria-dir, --criteria-repo, or run in a "
        "repo whose .graider.yml points at a criteria repo."
    )


@app.command()
def report(
    ctx: typer.Context,
    workspace: Optional[Path] = typer.Option(None, "--workspace"),
    grade_file: Path = typer.Option(Path("grade-results.json"), "--grade"),
    review_file: Path = typer.Option(Path("review-results.json"), "--review"),
    state: Optional[Path] = typer.Option(None, "--state"),
    out_dir: Path = typer.Option(Path("reports"), "--out-dir"),
) -> None:
    """Merge grade + review results into per-project reports and a CSV."""
    urls = project_urls(state)
    out_dir.mkdir(parents=True, exist_ok=True)

    dirs = (
        sorted(d for d in workspace.iterdir() if d.is_dir())
        if workspace is not None
        else [Path(".")]
    )

    rows: list[dict[str, object]] = []
    for directory in dirs:
        grades = {g.project: g for g in load_grades(directory / grade_file.name)}
        reviews = {r.project: r for r in load_reviews(directory / review_file.name)}
        names = list(grades) or list(reviews)
        for name in names:
            grade = grades.get(name)
            review = reviews.get(name)
            url = urls.get(name, "")
            (out_dir / f"{name}.md").write_text(render_report(grade, review, url), encoding="utf-8")
            rows.append(summary_row(grade, review, url))

    if not rows:
        raise GraiderError("No grade-results.json / review-results.json found to report on.")

    write_csv(rows, out_dir / "summary.csv")
    print_report_summary(rows, out_dir)
    print_success(f"Wrote {len(rows)} report(s) → {out_dir}")


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


@app.command()
def init(
    org: str = typer.Option("", "--org"),
    template: TemplateName = typer.Option(TemplateName.PYTHON, "--template"),
    course: str = typer.Option("course", "--course"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Scaffold a graider.toml in the current directory."""
    path = Path("graider.toml")
    if path.exists() and not force:
        raise GraiderError("graider.toml already exists; pass --force to overwrite.")
    path.write_text(
        f'gitlab_url = "https://gitlab.com"\n'
        f'org = "{org}"\n'
        f'template = "{template.value}"\n'
        f'course = "{course}"\n'
        f'roster = "students.csv"\n'
        f'state = "graider.lock.json"\n\n'
        f'[criteria]\nrepo = ""\npath = ""\n',
        encoding="utf-8",
    )
    print_success(f"Wrote {path} — edit it, then run `graider setup` with no flags.")


skills_app = typer.Typer(help="Install grAIder skills for Claude Code.")
app.add_typer(skills_app, name="skills")


def _install_skills(dest_root: Path) -> list[str]:
    from importlib.resources import files

    root = files("graider") / "skills"
    installed: list[str] = []
    for skill_dir in root.iterdir():
        if not skill_dir.is_dir():
            continue
        target = dest_root / skill_dir.name
        target.mkdir(parents=True, exist_ok=True)
        for item in skill_dir.iterdir():
            if item.is_file():
                (target / item.name).write_text(item.read_text(encoding="utf-8"), encoding="utf-8")
                installed.append(f"{skill_dir.name}/{item.name}")
    return installed


@skills_app.command("install")
def skills_install(
    target: Optional[Path] = typer.Option(
        None, "--dir", help="Skills directory (default: ~/.claude/skills)."
    ),
    project: bool = typer.Option(
        False, "--project", help="Install into ./.claude/skills instead of the user dir."
    ),
) -> None:
    """Install grAIder Agent Skills so Claude Code can drive the CLI."""
    dest = Path(".claude/skills") if project else (target or Path.home() / ".claude" / "skills")
    installed = _install_skills(dest)
    if not installed:
        raise GraiderError("No packaged skills found to install.")
    print_success(f"Installed {len(installed)} skill file(s) → {dest}")


criteria_app = typer.Typer(help="Author and validate grading criteria.")
app.add_typer(criteria_app, name="criteria")


@criteria_app.command("init")
def criteria_init(
    syllabus: Path = typer.Option(..., "--syllabus", exists=True, dir_okay=False),
    out: Path = typer.Option(..., "--out", help="Criteria repo directory to create."),
    model: str = typer.Option(CRITERIA_MODEL, "--model"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Draft a staggered-eval criteria repo from a syllabus."""
    draft = draft_criteria(syllabus, model=model)
    write_criteria_dir(draft, out, force=force)
    print_success(f"Drafted {len(draft.items)} criteria → {out} (released_up_to: 0)")


@criteria_app.command("check")
def criteria_check(
    criteria_dir: Path = typer.Argument(..., exists=True, file_okay=False),
) -> None:
    """Validate a criteria repo (ids, order, cutoff)."""
    problems = check_criteria_dir(criteria_dir)
    print_check_report(criteria_dir, problems)
    if problems:
        raise typer.Exit(code=1)


def run() -> None:
    try:
        app()
    except GraiderError as exc:
        print_error(str(exc))
        raise SystemExit(1) from exc
