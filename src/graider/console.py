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
