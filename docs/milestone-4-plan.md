# Milestone 4 — Detailed Implementation Plan

**Goal:** ship embedded starter templates for **python / java / cpp**, each with
a `.graider.yml`, a `qlty.toml`, a README linking the project brief, a
`.gitignore`, and a minimal GitLab CI — render them (with placeholder
substitution) into a set of files, and push them to a repo as the initial commit
via the GitLab commit API.

This document is prescriptive. Follow the steps in order. Where full code or file
content is given, you may copy it verbatim.

**Scope boundary:** Milestone 4 delivers (a) the template subsystem, (b) a
`graider template` command to list/render templates locally, and (c) a
`commit_files` primitive on `GitLabClient`. Wiring `setup` to create a project
per group and push the starter is **Milestone 5**. End-to-end "passing CI" is
validated here via a manual smoke test (render → push to a sandbox repo).

**Definition of done (verify all at the end):**

- `uv run graider template list` prints `python`, `java`, `cpp`.
- `uv run graider template render --template python --out ./out` writes a full
  starter tree; `./out/.graider.yml`, `./out/.gitignore`, `./out/qlty.toml`,
  `./out/README.md`, and `./out/.gitlab-ci.yml` all exist, and no output path
  ends in `.tmpl` or contains a `dot_` segment.
- `.graider.yml` content reflects the `--course`/`--criteria-repo`/
  `--criteria-path` flags.
- `GitLabClient.commit_files(...)` issues one commit-API call with one `create`
  action per file, and is a no-op in dry-run.
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`, and
  `uv run pytest` all pass. Crucially, the outer tooling must **not** try to
  lint/type-check/collect the template files (the `.tmpl` scheme below ensures
  this).

---

## Key design decision: the `.tmpl` + `dot_` storage scheme

Template files live under `src/graider/templates/<lang>/`. To stop the outer
project's tools (ruff, ty, pytest, uv) from ever interpreting a template as real
source, **every template file ends in `.tmpl`**, and any leading dot in a path
segment is stored as a `dot_` prefix. Rendering reverses both:

| Stored path (in the package) | Rendered path (in the student repo) |
|---|---|
| `python/dot_graider.yml.tmpl` | `.graider.yml` |
| `python/dot_gitignore.tmpl` | `.gitignore` |
| `python/dot_gitlab-ci.yml.tmpl` | `.gitlab-ci.yml` |
| `python/pyproject.toml.tmpl` | `pyproject.toml` |
| `python/src/main.py.tmpl` | `src/main.py` |

Because no stored file is named `*.py`, `pyproject.toml`, etc., ruff/ty/pytest/uv
ignore them automatically — **no exclude config needed**.

Placeholder substitution uses `{{key}}` (double braces — chosen to avoid
colliding with CMake `${VAR}` and CI `$CI_*`). Supported keys:
`project_name`, `course`, `template`, `criteria_repo`, `criteria_path`,
`brief_url`.

---

## Step 1 — Add the pyyaml… (do NOT)

No new dependency is required. `.graider.yml` is *written* as plain text via the
template — nothing here needs a YAML parser. (pyyaml arrives in Milestone 6/7
when `.graider.yml` is *read* for student self-assessment.)

---

## Step 2 — Target file layout

```
src/graider/
├── errors.py           # + TemplateError
├── models.py           # + RenderedFile
├── templates.py        # NEW: TemplateName, render_template, write_files
├── gitlab_client.py    # + commit_files()
├── cli.py              # + `template` command group
└── templates/          # NEW package data (see Step 6 for full contents)
    ├── python/…
    ├── java/…
    └── cpp/…
tests/
├── test_templates.py       # NEW
└── test_gitlab_client.py   # + commit_files tests
```

---

## Step 3 — `errors.py`: add `TemplateError`

```python
class TemplateError(GraiderError):
    """An unknown template was requested or a template could not be rendered."""
```

---

## Step 4 — `models.py`: add `RenderedFile`

Append (keeps `gitlab_client` from importing `templates`):

```python
class RenderedFile(BaseModel):
    path: str      # target path in the repo, e.g. ".graider.yml"
    content: str
```

---

## Step 5 — `src/graider/templates.py` (NEW)

```python
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
        raise TemplateError(
            f"Unknown template {language!r}; choose from {', '.join(TEMPLATES)}"
        )
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
```

---

## Step 6 — Template file contents

Create every file below **with a `.tmpl` suffix** at the given path under
`src/graider/templates/`. Directory separators are literal folders.

### 6a. Shared files (create the same three in `python/`, `java/`, and `cpp/`)

`<lang>/dot_graider.yml.tmpl`:

```yaml
course: {{course}}
template: {{template}}
criteria:
  repo: {{criteria_repo}}
  path: {{criteria_path}}
```

`<lang>/README.md.tmpl`:

```markdown
# {{project_name}}

Project brief: {{brief_url}}

Scaffolded by grAIder. Check your own work before submitting:

    graider grade
    graider review
```

### 6b. `python/`

`python/dot_gitignore.tmpl`:

```gitignore
__pycache__/
*.pyc
.venv/
dist/
build/
.pytest_cache/
.ruff_cache/
.qlty/
```

`python/pyproject.toml.tmpl`:

```toml
[project]
name = "{{project_name}}"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []

[dependency-groups]
dev = ["pytest>=8.0", "ruff>=0.6"]

[tool.uv]
package = false

[tool.ruff]
line-length = 100

[tool.pytest.ini_options]
pythonpath = ["src"]
```

`python/qlty.toml.tmpl`:

```toml
config_version = "0"

[[source]]
name = "default"
default = true

[[plugin]]
name = "ruff"
```

`python/src/calc.py.tmpl`:

```python
def add(a: int, b: int) -> int:
    return a + b


if __name__ == "__main__":
    print(add(2, 3))
```

`python/tests/test_calc.py.tmpl`:

```python
from calc import add


def test_add() -> None:
    assert add(2, 3) == 5
```

`python/dot_gitlab-ci.yml.tmpl`:

```yaml
stages: [test, quality]

test:
  image: ghcr.io/astral-sh/uv:python3.11-bookworm-slim
  stage: test
  script:
    - uv sync
    - uv run ruff check .
    - uv run pytest

quality:
  image: python:3.11
  stage: quality
  script:
    - curl https://qlty.sh | sh
    - export PATH="$HOME/.qlty/bin:$PATH"
    - qlty check --all --no-fail
  allow_failure: true
```

### 6c. `java/`

`java/dot_gitignore.tmpl`:

```gitignore
.gradle/
build/
.qlty/
```

`java/settings.gradle.kts.tmpl`:

```kotlin
rootProject.name = "{{project_name}}"
```

`java/build.gradle.kts.tmpl`:

```kotlin
plugins {
    application
}

repositories { mavenCentral() }

dependencies {
    testImplementation("org.junit.jupiter:junit-jupiter:5.10.2")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}

application { mainClass.set("App") }

tasks.test { useJUnitPlatform() }
```

`java/qlty.toml.tmpl`:

```toml
config_version = "0"

[[source]]
name = "default"
default = true

[[plugin]]
name = "checkstyle"
```

`java/src/main/java/App.java.tmpl`:

```java
public class App {
    public static int add(int a, int b) {
        return a + b;
    }

    public static void main(String[] args) {
        System.out.println(add(2, 3));
    }
}
```

`java/src/test/java/AppTest.java.tmpl`:

```java
import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class AppTest {
    @Test
    void addsNumbers() {
        assertEquals(5, App.add(2, 3));
    }
}
```

`java/dot_gitlab-ci.yml.tmpl`:

```yaml
stages: [test, quality]

test:
  image: gradle:8.7-jdk21
  stage: test
  script:
    - gradle test --no-daemon

quality:
  image: python:3.11
  stage: quality
  script:
    - curl https://qlty.sh | sh
    - export PATH="$HOME/.qlty/bin:$PATH"
    - qlty check --all --no-fail
  allow_failure: true
```

> The Gradle **wrapper** (`gradlew` + `gradle-wrapper.jar`) is intentionally not
> bundled — a binary jar complicates packaging. The CI uses the `gradle` image
> instead. If you later want the wrapper, generate it in Milestone 5's push step
> or add it as base64 package data.

### 6d. `cpp/`

`cpp/dot_gitignore.tmpl`:

```gitignore
build/
.qlty/
```

`cpp/CMakeLists.txt.tmpl`:

```cmake
cmake_minimum_required(VERSION 3.20)
project({{project_name}} CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(FetchContent)
FetchContent_Declare(
  Catch2
  GIT_REPOSITORY https://github.com/catchorg/Catch2.git
  GIT_TAG v3.5.2
)
FetchContent_MakeAvailable(Catch2)

add_library(calc src/calc.cpp)
target_include_directories(calc PUBLIC src)

enable_testing()
add_executable(unit_tests tests/test_calc.cpp)
target_link_libraries(unit_tests PRIVATE calc Catch2::Catch2WithMain)

list(APPEND CMAKE_MODULE_PATH ${Catch2_SOURCE_DIR}/extras)
include(CTest)
include(Catch)
catch_discover_tests(unit_tests)
```

`cpp/qlty.toml.tmpl`:

```toml
config_version = "0"

[[source]]
name = "default"
default = true

[[plugin]]
name = "clang-tidy"
```

`cpp/src/calc.hpp.tmpl`:

```cpp
#pragma once

int add(int a, int b);
```

`cpp/src/calc.cpp.tmpl`:

```cpp
#include "calc.hpp"

int add(int a, int b) {
    return a + b;
}
```

`cpp/tests/test_calc.cpp.tmpl`:

```cpp
#include <catch2/catch_test_macros.hpp>

#include "calc.hpp"

TEST_CASE("adds numbers") {
    REQUIRE(add(2, 3) == 5);
}
```

`cpp/dot_gitlab-ci.yml.tmpl`:

```yaml
stages: [test, quality]

test:
  image: gcc:13
  stage: test
  script:
    - apt-get update && apt-get install -y cmake
    - cmake -B build
    - cmake --build build
    - ctest --test-dir build --output-on-failure

quality:
  image: python:3.11
  stage: quality
  script:
    - curl https://qlty.sh | sh
    - export PATH="$HOME/.qlty/bin:$PATH"
    - qlty check --all --no-fail
  allow_failure: true
```

> **The `qlty.toml` files are best-effort.** qlty's config schema is authoritative
> from `qlty init`. After Step 9, run `qlty init` in a rendered project for each
> language and reconcile the generated `qlty.toml` with the ones above if they
> differ (plugin names / `config_version`). Keep `quality` jobs `allow_failure:
> true` so CI stays green regardless.

---

## Step 7 — `gitlab_client.py`: add `commit_files`

Add the import and method:

```python
from graider.models import InviteResult, InviteStatus, ProjectRef, RenderedFile
```

```python
    def commit_files(
        self,
        project_id: int,
        files: list[RenderedFile],
        *,
        message: str = "Initial commit",
        branch: str = "main",
    ) -> None:
        """Create/overwrite files in a single commit. No-op in dry-run.

        For an empty repository this first commit creates `branch`.
        """
        if self.dry_run:
            return
        actions = [
            {"action": "create", "file_path": f.path, "content": f.content}
            for f in files
        ]
        project = self._gl.projects.get(project_id, lazy=True)
        try:
            project.commits.create(
                {"branch": branch, "commit_message": message, "actions": actions}
            )
        except GitlabCreateError as exc:
            raise GitLabError(
                f"Could not push initial commit to project {project_id}: {exc}"
            ) from exc
```

---

## Step 8 — `cli.py`: add the `template` command group

Add imports:

```python
from graider.templates import (
    TemplateContext,
    TemplateName,
    render_template,
    write_files,
)
```

Add after the existing commands:

```python
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
```

> No changes to `setup` this milestone. `render_template` + `commit_files` are
> what Milestone 5 calls per group.

---

## Step 9 — Tests

### `tests/test_templates.py` (NEW)

```python
import pytest

from graider.errors import TemplateError
from graider.templates import (
    TEMPLATES,
    TemplateContext,
    render_template,
    write_files,
)


def _by_path(language, **kw):
    ctx = TemplateContext(**kw)
    return {f.path: f.content for f in render_template(language, ctx)}


def test_templates_list():
    assert set(TEMPLATES) == {"python", "java", "cpp"}


def test_unknown_template_raises():
    with pytest.raises(TemplateError, match="Unknown template"):
        render_template("rust", TemplateContext())


@pytest.mark.parametrize("language", TEMPLATES)
def test_every_language_has_core_files(language):
    files = _by_path(language)
    assert ".graider.yml" in files
    assert ".gitignore" in files
    assert ".gitlab-ci.yml" in files
    assert "qlty.toml" in files
    assert "README.md" in files


@pytest.mark.parametrize("language", TEMPLATES)
def test_no_tmpl_or_dot_prefix_leaks(language):
    for path in _by_path(language):
        assert not path.endswith(".tmpl"), path
        assert "dot_" not in path, path


def test_graider_yml_substitution():
    files = _by_path(
        "python", course="swe25", criteria_repo="https://gl/swe/crit",
        criteria_path="swe25/",
    )
    yml = files[".graider.yml"]
    assert "course: swe25" in yml
    assert "template: python" in yml
    assert "repo: https://gl/swe/crit" in yml
    assert "path: swe25/" in yml
    assert "{{" not in yml  # every placeholder resolved


def test_write_files(tmp_path):
    rendered = render_template("python", TemplateContext())
    write_files(rendered, tmp_path)
    assert (tmp_path / ".graider.yml").exists()
    assert (tmp_path / "src" / "calc.py").exists()
```

### `tests/test_gitlab_client.py` (ADD)

```python
from graider.models import RenderedFile


def test_commit_files(fake_gl):
    files = [
        RenderedFile(path=".graider.yml", content="a"),
        RenderedFile(path="src/calc.py", content="b"),
    ]
    GitLabClient("https://gl", "t").commit_files(1, files)
    payload = fake_gl.projects.get.return_value.commits.create.call_args[0][0]
    assert payload["branch"] == "main"
    assert {a["file_path"] for a in payload["actions"]} == {".graider.yml", "src/calc.py"}
    assert all(a["action"] == "create" for a in payload["actions"])


def test_commit_files_dry_run(fake_gl):
    files = [RenderedFile(path="x", content="y")]
    GitLabClient("https://gl", "t", dry_run=True).commit_files(1, files)
    fake_gl.projects.get.assert_not_called()
```

---

## Step 10 — Verify packaging (important)

The templates must ship inside the wheel, or `render_template` will fail once
installed (not just in editable dev mode). Build and inspect:

```sh
uv build
python -c "import zipfile, glob; w=glob.glob('dist/*.whl')[0]; print('\n'.join(n for n in zipfile.ZipFile(w).namelist() if 'templates/' in n))"
```

You should see every `.tmpl` file listed. If the list is **empty**, uv_build did
not include the data files — add package-data inclusion for
`src/graider/templates/**` (consult the uv_build docs for the include key) and
rebuild until they appear. Then clean up: `rm -rf dist`.

---

## Step 11 — Verify everything

```sh
uv sync
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest -q

uv run graider template list
uv run graider template render --template python --out /tmp/starter \
    --course swe25 --criteria-repo https://gitlab.com/swe/criteria --criteria-path swe25/
cat /tmp/starter/.graider.yml     # placeholders resolved
ls -A /tmp/starter                # .graider.yml .gitignore .gitlab-ci.yml qlty.toml README.md pyproject.toml src tests
```

If `ruff check`/`ty check` reports anything inside `src/graider/templates/`, a
template file was stored **without** the `.tmpl` suffix — rename it.

---

## Step 12 — Manual smoke test (optional, validates "passing CI")

```sh
uv run graider template render --template python --out /tmp/starter --course swe25
cd /tmp/starter
git init && git add -A && git commit -m "starter"
git push to a sandbox GitLab project you own
# watch the pipeline: `test` should pass, `quality` runs qlty (allow_failure).
```

For the real API-push path, exercise `GitLabClient.commit_files` against a
throwaway project in a REPL (see Milestone 3's smoke-test snippet), then delete
the project.

---

## Notes for the next milestone

- **Milestone 5 (orchestration)** per group: `create_project` → build a
  `TemplateContext` (project_name = the random name, course/criteria from CLI
  flags) → `render_template` → `commit_files` → `protect_branch("main")` →
  `invite_member` for each student → record `ProjectRef` + `InviteResult`s into
  the state file. `protect_branch` must run **after** `commit_files`, since an
  empty repo has no `main` to protect.
- The `--template`, `--course`, `--criteria-repo`, `--criteria-path`,
  `--brief-url` options added to `template render` here are the same ones
  Milestone 5 adds to `setup`; keep their names identical.
- If a group needs a per-project brief URL, compute it in Milestone 5 before
  rendering and pass it as `brief_url`.
```
