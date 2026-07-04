"""Shared Rich consoles and output helpers."""

from pathlib import Path

from rich.console import Console
from rich.table import Table

from graider.models import (
    CriteriaItem,
    GradeResult,
    Group,
    InviteResult,
    InviteStatus,
    ReviewResult,
    SetupState,
    Student,
    Usage,
)
from graider.pricing import estimate_cost

console = Console()
err_console = Console(stderr=True)


def print_error(message: str) -> None:
    err_console.print(f"[bold red]✗[/] {message}")


def print_warning(message: str) -> None:
    err_console.print(f"[bold yellow]![/] {message}")


def print_success(message: str) -> None:
    console.print(f"[bold green]✓[/] {message}")


def print_report_summary(rows: list[dict[str, object]], out_dir: Path) -> None:
    table = Table(title="Report")
    table.add_column("Project", style="bold")
    table.add_column("Tests", justify="right")
    table.add_column("Cov %", justify="right")
    table.add_column("Criteria", justify="right")
    for row in rows:
        tests = f"{row['tests_passed']}/{row['tests_failed']}" if row["tests_passed"] != "" else "-"
        cov = row["coverage_percent"] if row["coverage_percent"] != "" else "-"
        crit = (
            f"{row['criteria_met']}/{row['criteria_total']}" if row["criteria_total"] != "" else "-"
        )
        table.add_row(str(row["project"]), str(tests), str(cov), str(crit))
    console.print(table)


def print_check_report(criteria_dir: Path, problems: list[str]) -> None:
    if not problems:
        print_success(f"{criteria_dir}: criteria OK")
        return
    err_console.print(f"[bold red]✗[/] {criteria_dir}: {len(problems)} problem(s)")
    for problem in problems:
        err_console.print(f"  • {problem}")


def print_groups(groups: list[Group]) -> None:
    table = Table(title="Roster")
    table.add_column("Group", style="bold")
    table.add_column("Members")
    table.add_column("#", justify="right")
    for group in groups:
        members = "\n".join(m.email for m in group.members)
        table.add_row(group.number, members, str(len(group.members)))
    console.print(table)


_INVITE_STYLE = {
    InviteStatus.INVITED: ("[green]✓ invited[/]", ""),
    InviteStatus.ALREADY_MEMBER: ("[dim]• already a member[/]", ""),
    InviteStatus.NO_ACCOUNT: ("[yellow]! no GitLab account[/]", ""),
    InviteStatus.SKIPPED: ("[dim]— skipped (dry run)[/]", ""),
}


def print_invite_results(results: list[InviteResult]) -> None:
    table = Table(title="Invitations")
    table.add_column("Email")
    table.add_column("Status")
    table.add_column("Username")
    for result in results:
        label, _ = _INVITE_STYLE.get(result.status, (result.status.value, ""))
        table.add_row(result.email, label, result.username or "")
    console.print(table)


def print_setup_preview(rows: list[tuple[str, str, list[Student]]]) -> None:
    """rows: (group_number, project_name, members)."""
    table = Table(title="Setup preview (dry run)")
    table.add_column("Group", style="bold")
    table.add_column("Project name")
    table.add_column("Members")
    for group_number, name, members in rows:
        emails = "\n".join(s.email for s in members)
        table.add_row(group_number, name, emails)
    console.print(table)


def print_project_summary(state: SetupState) -> None:
    table = Table(title="Projects")
    table.add_column("Group", style="bold")
    table.add_column("Project")
    table.add_column("URL")
    table.add_column("Invited", justify="right")
    table.add_column("Needs account", justify="right")
    for group_number, project in sorted(state.projects.items()):
        ok = sum(
            m.status in (InviteStatus.INVITED, InviteStatus.ALREADY_MEMBER) for m in project.members
        )
        missing = sum(m.status == InviteStatus.NO_ACCOUNT for m in project.members)
        table.add_row(
            group_number,
            project.name,
            project.web_url,
            f"{ok}/{len(project.members)}",
            str(missing) or "",
        )
    console.print(table)


def print_grade_table(results: list[GradeResult]) -> None:
    table = Table(title="Grades")
    table.add_column("Project", style="bold")
    table.add_column("Tmpl")
    table.add_column("Tests", justify="right")
    table.add_column("Cov %", justify="right")
    table.add_column("Issues", justify="right")
    table.add_column("Smells", justify="right")
    table.add_column("Notes")
    for r in results:
        tests = (
            f"[green]{r.tests_passed}[/]"
            if r.tests_failed == 0
            else (f"[red]{r.tests_passed}/{r.tests_passed + r.tests_failed}[/]")
        )
        cov = "-" if r.coverage_percent is None else f"{r.coverage_percent}"
        table.add_row(
            r.project,
            r.template,
            tests,
            cov,
            str(r.qlty_issues),
            str(r.qlty_smells),
            "; ".join(r.errors),
        )
    console.print(table)


def print_criteria_scope(in_scope: list[CriteriaItem], out_scope: list[CriteriaItem]) -> None:
    table = Table(title="Criteria")
    table.add_column("#", justify="right")
    table.add_column("ID")
    table.add_column("Title")
    table.add_column("Scope")
    for item in in_scope:
        table.add_row(str(item.order), item.id, item.title, "[green]in scope[/]")
    for item in out_scope:
        table.add_row(str(item.order), item.id, item.title, "[dim]not yet evaluated[/]")
    console.print(table)


def print_review(result: ReviewResult) -> None:
    table = Table(title=f"Review — {result.project}")
    table.add_column("ID")
    table.add_column("Criterion")
    table.add_column("Met")
    table.add_column("Comment")
    for verdict in result.criteria:
        met = "[green]✓[/]" if verdict.met else "[red]✗[/]"
        table.add_row(verdict.id, verdict.title, met, verdict.comment)
    console.print(table)
    console.print(f"\n[bold]Summary:[/] {result.overall_summary}")


def print_usage(usage: Usage, model: str) -> None:
    cost = estimate_cost(model, usage)
    tail = f" — est. ${cost:.4f}" if cost is not None else ""
    console.print(f"[dim]Tokens: {usage.input_tokens:,} in / {usage.output_tokens:,} out{tail}[/]")
