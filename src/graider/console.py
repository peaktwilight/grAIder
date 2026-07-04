"""Shared Rich consoles and output helpers."""

from rich.console import Console
from rich.table import Table

from graider.models import Group

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
