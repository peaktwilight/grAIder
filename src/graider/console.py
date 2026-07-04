"""Shared Rich consoles and output helpers."""

from rich.console import Console
from rich.table import Table

from graider.models import Group, InviteResult, InviteStatus, SetupState, Student

console = Console()
err_console = Console(stderr=True)


def print_error(message: str) -> None:
    err_console.print(f"[bold red]✗[/] {message}")


def print_warning(message: str) -> None:
    err_console.print(f"[bold yellow]![/] {message}")


def print_success(message: str) -> None:
    console.print(f"[bold green]✓[/] {message}")


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
