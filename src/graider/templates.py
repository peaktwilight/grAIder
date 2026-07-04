"""Starter templates: discover, render (with {{placeholder}} substitution)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from importlib.resources import files
from pathlib import Path

from graider.errors import TemplateError
from graider.models import RenderedFile


class TemplateName(StrEnum):
    PYTHON = "python"
    JAVA = "java"
    CPP = "cpp"
    GO = "go"


TEMPLATES: tuple[str, ...] = tuple(t.value for t in TemplateName)


@dataclass(frozen=True)
class TemplateContext:
    project_name: str = "project"
    course: str = "course"
    criteria_repo: str = ""
    criteria_path: str = ""
    brief_url: str = ""


def render_template(language: str, context: TemplateContext) -> list[RenderedFile]:
    if language not in TEMPLATES:
        raise TemplateError(f"Unknown template {language!r}; choose from {', '.join(TEMPLATES)}")
    ctx = {**asdict(context), "template": language}
    root = files("graider") / "templates" / language
    return [
        RenderedFile(path=_target_path(rel), content=_substitute(text, ctx))
        for rel, text in _iter_files(root)
    ]


def write_files(rendered: list[RenderedFile], out_dir: Path) -> None:
    for item in rendered:
        dest = out_dir / item.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(item.content, encoding="utf-8")


# --- internals ---------------------------------------------------------------


def _iter_files(traversable, prefix: str = ""):
    for entry in traversable.iterdir():
        rel = f"{prefix}{entry.name}"
        if entry.is_dir():
            yield from _iter_files(entry, prefix=f"{rel}/")
        else:
            yield rel, entry.read_text(encoding="utf-8")


def _target_path(rel: str) -> str:
    segments = []
    for seg in rel.split("/"):
        if seg.startswith("dot_"):
            seg = "." + seg[len("dot_") :]
        segments.append(seg)
    path = "/".join(segments)
    if path.endswith(".tmpl"):
        path = path[: -len(".tmpl")]
    return path


def _substitute(text: str, ctx: dict[str, str]) -> str:
    for key, value in ctx.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text
