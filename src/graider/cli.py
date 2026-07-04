"""graider command-line interface."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

import click
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
    print_usage,
    print_warning,
)
from graider.criteria import (
    fetch_criteria_repo,
    load_criteria_dir,
    released_cutoff,
    split_by_cutoff,
)
from graider.errors import GraiderError
from graider.feedback.render import REVIEW_MARKER, issue_title, render_feedback
from graider.gitlab_client import GitLabClient
from graider.grading.runner import grade_project
from graider.interview.agent import generate_interview, render_interview_md, select_topics
from graider.models import MemberState, ProjectState, ReviewResult
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
from graider.review.agent import DEFAULT_MODEL, review_project, select_backend
from graider.review.cache import ReviewCache
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
def calibrate(
    ctx: typer.Context,
    repo: Path = typer.Option(Path("."), "--repo", help="The benchmark submission."),
    criteria_dir: Optional[Path] = typer.Option(None, "--criteria-dir"),
    criteria_repo: str = typer.Option("", "--criteria-repo"),
    criteria_path: str = typer.Option("", "--criteria-path"),
    name: str = typer.Option("", "--name", help="Anchor name (default: repo dir name)."),
    level: Optional[list[str]] = typer.Option(
        None, "--level", help="Teacher level as ID=LEVEL (repeatable)."
    ),
    up_to: Optional[str] = typer.Option(None, "--up-to"),
    note: str = typer.Option("", "--note"),
    check: bool = typer.Option(False, "--check", help="Run the AI on it and report drift."),
    model: str = typer.Option(DEFAULT_MODEL, "--model"),
    backend: str = typer.Option("auto", "--backend"),
) -> None:
    """Record a teacher-graded benchmark submission to calibrate the model."""
    from graider.authoring.anchors import agreement, save_anchor
    from graider.models import Anchor, PerformanceLevel

    source = _resolve_criteria_dir(repo, criteria_dir, criteria_repo, criteria_path)
    if criteria_dir is None:
        raise GraiderError("calibrate needs a local --criteria-dir to store the anchor.")
    criteria = load_criteria_dir(source)
    cutoff: str | int | None = up_to if up_to is not None else released_cutoff(source)
    in_scope, _ = split_by_cutoff(criteria.items, cutoff)

    valid = {lvl.value for lvl in PerformanceLevel}
    levels: dict[str, str] = {}
    provided = {}
    for pair in level or []:
        if "=" in pair:
            cid, lvl = pair.split("=", 1)
            provided[cid.strip()] = lvl.strip().lower()
    for item in in_scope:
        chosen = provided.get(item.id)
        if chosen is None:
            prompt_text = f"Level for {item.id}. {item.title} ({'/'.join(valid)})"
            chosen = typer.prompt(prompt_text).strip().lower()
        if chosen not in valid:
            raise GraiderError(f"criterion {item.id}: {chosen!r} is not a level ({sorted(valid)}).")
        levels[item.id] = chosen

    anchor = Anchor(name=name or repo.resolve().name, levels=levels, note=note)

    if check:
        be = select_backend(backend)
        result = review_project(
            repo, criteria.brief, in_scope, cutoff=str(cutoff or ""), model=model, backend=be
        )
        agree, total, disagreements = agreement(anchor, result.criteria)
        console.print(f"Model agreement with your grades: {agree}/{total}")
        for d in disagreements:
            print_warning(d)

    save_anchor(criteria_dir, anchor)
    print_success(f"Saved anchor {anchor.name!r} → {criteria_dir}/anchors.yml")


review_app = typer.Typer(
    help="Draft an AI review (default) and, after teacher approval, publish it.",
    invoke_without_command=True,
)
app.add_typer(review_app, name="review")


@review_app.callback(invoke_without_command=True)
def review(
    ctx: typer.Context,
    repo: Path = typer.Option(Path("."), "--repo"),
    criteria_dir: Optional[Path] = typer.Option(None, "--criteria-dir"),
    criteria_repo: str = typer.Option("", "--criteria-repo"),
    criteria_path: str = typer.Option("", "--criteria-path"),
    up_to: Optional[str] = typer.Option(None, "--up-to", help="Position or item id."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    model: str = typer.Option(DEFAULT_MODEL, "--model", help="Claude model id."),
    force: bool = typer.Option(
        False, "--force", help="Ignore any cached result and re-run the model."
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Ignore the review cache and always call the model."
    ),
    formative: bool = typer.Option(
        False, "--formative", help="Formative self-check tone (growth, not a grade)."
    ),
    results: Path = typer.Option(Path("review-results.json"), "--results"),
    backend: str = typer.Option(
        "auto", "--backend", help="auto | api | claude-code | openai | gemini | glm."
    ),
) -> None:
    """Draft a review of a repo against the (staggered) criteria.

    Writes review-results.json as an unpublished DRAFT. Nothing reaches students
    until a teacher runs `graider review publish`.
    """
    if ctx.invoked_subcommand is not None:
        return  # a subcommand (e.g. `publish`) is handling this invocation
    config = _config(ctx)
    source = _resolve_criteria_dir(repo, criteria_dir, criteria_repo, criteria_path)
    criteria = load_criteria_dir(source)
    from graider.authoring.anchors import load_anchors

    anchors = load_anchors(source)

    cutoff: str | int | None = up_to if up_to is not None else released_cutoff(source)
    in_scope, out_scope = split_by_cutoff(criteria.items, cutoff)

    if dry_run or config.dry_run:
        print_criteria_scope(in_scope, out_scope)
        print_success(f"{len(in_scope)} of {len(criteria.items)} criteria in scope (dry run).")
        return

    results_path = results
    cache = (
        None
        if no_cache
        else ReviewCache.load(results_path.with_name(results_path.stem + ".cache.json"))
    )

    prior = None
    if results_path.exists():
        try:
            prior = ReviewResult.model_validate_json(results_path.read_text(encoding="utf-8"))
        except ValueError:
            prior = None

    be = select_backend(backend)
    result = review_project(
        repo,
        criteria.brief,
        in_scope,
        cutoff=str(cutoff) if cutoff is not None else "",
        model=model,
        backend=be,
        cache=cache,
        refresh=force,
        prior=prior,
        formative=formative,
        anchors=anchors,
    )
    print_review(result)
    for warning in result.warnings:
        print_warning(warning)
    results_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    if cache is not None and cache.last_hit:
        console.print("[dim](loaded from cache; pass --force or --no-cache to re-run)[/]")
    else:
        print_success(f"Drafted review of {len(in_scope)} criteria → {results_path}")
    if be.last_usage:
        print_usage(be.last_usage, model)
    console.print("[dim]Review it, then run `graider review publish` to post to GitLab.[/]")


@review_app.command("publish")
def review_publish(
    ctx: typer.Context,
    results: Path = typer.Option(Path("review-results.json"), "--results"),
    feedback: str = typer.Option("mr", "--feedback", help="Post as: mr | issue."),
    project_id: str = typer.Option("", "--project-id", help="GitLab project id/path."),
    mr_iid: int = typer.Option(0, "--mr-iid", help="Merge request iid (for --feedback mr)."),
    branch: str = typer.Option("", "--branch", help="Source branch to find the open MR."),
    yes: bool = typer.Option(False, "--yes", help="Approve and post without prompting."),
    force: bool = typer.Option(False, "--force", help="Re-post even if already published."),
) -> None:
    """Review the drafted feedback and, once a teacher approves, post it to GitLab.

    The teacher is the grader of record: the AI only drafts. Approve as shown,
    edit in $EDITOR, or skip — nothing is posted until you approve.
    """
    config = _config(ctx)
    if not results.exists():
        raise GraiderError(f"No draft found at {results}; run `graider review` first.")
    result = ReviewResult.model_validate_json(results.read_text(encoding="utf-8"))
    if result.published and not force:
        print_warning(f"Already published at {result.published_at}; pass --force to re-post.")
        return

    body = render_feedback(result)
    console.print(body)
    for warning in result.warnings:
        print_warning(warning)

    if not yes:
        choice = typer.prompt("Approve and post? [a]pprove / [e]dit / [s]kip", default="s")
        if choice[:1].lower() == "e":
            edited = click.edit(body)
            if edited is not None:
                body = edited
        elif choice[:1].lower() != "a":
            print_warning("Skipped; nothing posted.")
            return

    _post_feedback(config, result, body, feedback, project_id, mr_iid, branch)
    result.published = True
    result.published_at = datetime.now(UTC).isoformat()
    results.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")


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


def _post_feedback(
    config: Config,
    result: ReviewResult,
    body: str,
    feedback: str,
    project_id: str,
    mr_iid: int,
    branch: str,
) -> None:
    """Post the (teacher-approved) feedback body to a GitLab MR note or issue."""
    if feedback not in ("mr", "issue"):
        raise GraiderError(f"Unknown --feedback {feedback!r}; use mr | issue.")
    if not project_id:
        raise GraiderError("--feedback needs --project-id (the GitLab project id or path).")
    token = require_token(config)
    client = GitLabClient(config.gitlab_url, token, dry_run=config.dry_run)
    if feedback == "issue":
        client.upsert_issue(project_id, issue_title(result), body, REVIEW_MARKER)
        print_success(f"Posted review as an issue on {project_id}.")
        return
    iid = mr_iid or (client.find_open_mr_iid(project_id, branch) if branch else None)
    if not iid:
        raise GraiderError("--feedback mr needs --mr-iid or --branch with an open merge request.")
    client.upsert_mr_note(project_id, iid, body, REVIEW_MARKER)
    print_success(f"Posted review to MR !{iid} on {project_id}.")


@app.command()
def interview(
    ctx: typer.Context,
    repo: Path = typer.Option(Path("."), "--repo", help="Student project repo."),
    criteria_dir: Optional[Path] = typer.Option(None, "--criteria-dir"),
    criteria_repo: str = typer.Option("", "--criteria-repo"),
    criteria_path: str = typer.Option("", "--criteria-path"),
    topic: Optional[list[str]] = typer.Option(
        None, "--topic", help="Topic id or title substring (repeatable). Omit for all."
    ),
    prompt: str = typer.Option("", "--prompt", help="Extra guidance to steer the questions."),
    per_topic: int = typer.Option(3, "--per-topic", help="Questions per topic."),
    out: Path = typer.Option(Path("interview.md"), "--out"),
    model: str = typer.Option(DEFAULT_MODEL, "--model"),
    backend: str = typer.Option(
        "auto", "--backend", help="auto | api | claude-code | openai | gemini | glm."
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Generate viva questions probing a student's understanding of their project."""
    config = _config(ctx)
    source = _resolve_criteria_dir(repo, criteria_dir, criteria_repo, criteria_path)
    criteria = load_criteria_dir(source)
    topics = select_topics(criteria.items, list(topic or []))

    if dry_run or config.dry_run:
        console.print("Topics to examine:")
        for item in topics:
            console.print(f"  {item.id}. {item.title}")
        print_success(f"{len(topics)} topic(s) (dry run, no questions generated).")
        return

    be = select_backend(backend)
    output = generate_interview(
        repo,
        criteria.brief,
        topics,
        guidance=prompt,
        per_topic=per_topic,
        model=model,
        backend=be,
    )
    out.write_text(render_interview_md(repo.resolve().name, output), encoding="utf-8")
    total = sum(len(t.questions) for t in output.topics)
    print_success(f"Wrote {total} questions across {len(topics)} topic(s) → {out}")
    if be.last_usage:
        print_usage(be.last_usage, model)


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
    backend: str = typer.Option(
        "auto", "--backend", help="auto | api | claude-code | openai | gemini | glm."
    ),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Draft a staggered-eval criteria repo from a syllabus."""
    be = select_backend(backend)
    draft = draft_criteria(syllabus, model=model, backend=be)
    write_criteria_dir(draft, out, force=force)
    print_success(f"Drafted {len(draft.items)} criteria → {out} (released_up_to: 0)")
    if be.last_usage:
        print_usage(be.last_usage, model)


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
