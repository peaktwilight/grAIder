"""Integration tests: render each starter and build + test it with a real toolchain.

These are marked `integration` (deselected by default via addopts) and skip when
the required toolchain is missing, so a plain `uv run pytest` stays fast and
offline. CI runs them per-language in the matching Docker image; locally run
`uv run pytest -m integration` (needs uv / gradle / cmake installed) or
`scripts/check-starters.sh` (needs only Docker).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from graider.templates import TemplateContext, render_template, write_files

pytestmark = pytest.mark.integration


def _render(tmp_path: Path, language: str) -> Path:
    out = tmp_path / language
    write_files(render_template(language, TemplateContext(project_name="demo")), out)
    return out


def _run(cmd: list[str], cwd: Path) -> None:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(
            f"$ {' '.join(cmd)}  (in {cwd})\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )


def _have(*tools: str) -> bool:
    return all(shutil.which(tool) for tool in tools)


@pytest.mark.skipif(not _have("uv"), reason="uv not installed")
def test_python_starter(tmp_path: Path) -> None:
    out = _render(tmp_path, "python")
    _run(["uv", "sync"], out)
    _run(["uv", "run", "ruff", "check", "."], out)
    _run(["uv", "run", "pytest"], out)


@pytest.mark.skipif(not _have("gradle"), reason="gradle not installed")
def test_java_starter(tmp_path: Path) -> None:
    out = _render(tmp_path, "java")
    _run(["gradle", "test", "--no-daemon"], out)


@pytest.mark.skipif(not _have("cmake", "git"), reason="cmake/git not installed")
def test_cpp_starter(tmp_path: Path) -> None:
    out = _render(tmp_path, "cpp")
    _run(["cmake", "-B", "build"], out)
    _run(["cmake", "--build", "build"], out)
    _run(["ctest", "--test-dir", "build", "--output-on-failure"], out)
