# Extension E1 — Context-aware configuration (detailed plan)

**Goal:** a project-level `graider.toml`, discovered by walking up from the
current directory, supplies defaults for `--org`, `--roster`, `--template`,
`--criteria-repo/path`, `--name-prefix`, `--state`, `--course`, `--brief-url`,
`--gitlab-url` — so a teacher runs bare commands inside a configured course
directory. CLI flags and env vars still win.

Builds on Milestone 1 (`config.py` / `resolve_config`) and the commands from
Milestones 5–10.

**Definition of done:**

- With a `graider.toml` in (or above) the cwd, `graider setup`, `grade`,
  `review`, and `report` pick up its values when the corresponding flag is
  omitted.
- Precedence per field: **CLI flag → env var → `graider.toml` → global
  `~/.config/graider/config.toml` → built-in default.**
- `graider init` scaffolds a `graider.toml` in the current directory.
- `ruff`, `ruff format --check`, `ty`, `pytest` pass; config resolution is
  unit-tested per layer.

> **Do not confuse** `graider.toml` (instructor context, this feature) with
> `.graider.yml` (per-student-repo self-assessment pointer, Milestone 4) — they
> are different files read by different code paths.

---

## Step 1 — `graider.toml` schema

```toml
gitlab_url = "https://gitlab.com"
org = "swe/2026"
roster = "students.xlsx"
template = "python"
course = "swe25"
name_prefix = "swe25"
state = "graider.lock.json"
brief_url = "https://gitlab.com/swe/criteria/-/blob/main/swe25/brief.md"

[criteria]
repo = "https://gitlab.com/swe/criteria"
path = "swe25/"
```

All keys optional. Paths are resolved relative to the directory that contains
the `graider.toml` (so a command run in a subdirectory still finds `students.xlsx`).

---

## Step 2 — `config.py`: discovery + model + merge

Add a `ProjectFile` model, upward discovery, and fold it into `resolve_config`.

```python
class ProjectFile(BaseModel):
    dir: Path                      # the directory containing graider.toml
    gitlab_url: str | None = None
    org: str = ""
    roster: str = ""
    template: str = ""
    course: str = ""
    name_prefix: str = ""
    state: str = ""
    brief_url: str = ""
    criteria_repo: str = ""
    criteria_path: str = ""

    def path(self, value: str) -> Path | None:
        """Resolve a relative path value against the config dir."""
        return (self.dir / value) if value else None


def find_project_file(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        candidate = directory / "graider.toml"
        if candidate.exists():
            return candidate
    return None


def load_project_file(path: Path) -> ProjectFile:
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"Could not read {path}: {exc}") from exc
    criteria = data.get("criteria") or {}
    return ProjectFile(
        dir=path.parent,
        gitlab_url=data.get("gitlab_url"),
        org=data.get("org", ""),
        roster=data.get("roster", ""),
        template=data.get("template", ""),
        course=data.get("course", ""),
        name_prefix=data.get("name_prefix", ""),
        state=data.get("state", ""),
        brief_url=data.get("brief_url", ""),
        criteria_repo=criteria.get("repo", ""),
        criteria_path=criteria.get("path", ""),
    )
```

Extend `Config` to carry the discovered project file, and make `resolve_config`
insert `graider.toml`'s `gitlab_url` into the precedence (below env, above the
global file / default):

```python
class Config(BaseModel):
    gitlab_url: str
    token: str | None = None
    dry_run: bool = False
    project: ProjectFile | None = None
```

```python
def resolve_config(*, token, gitlab_url, config_path, dry_run=False, project_start=None):
    file_data = load_config_file(config_path)
    project_path = find_project_file(project_start)
    project = load_project_file(project_path) if project_path else None

    resolved_url = (
        gitlab_url
        or (project.gitlab_url if project else None)
        or file_data.get("gitlab_url")
        or DEFAULT_GITLAB_URL
    )
    resolved_token = token or file_data.get("token")
    return Config(
        gitlab_url=resolved_url, token=resolved_token, dry_run=dry_run, project=project
    )
```

> The callback passes nothing new — `resolve_config` discovers `graider.toml`
> from the cwd by default. Add an optional `project_start` param only so tests can
> point discovery at a temp dir.

---

## Step 3 — `cli.py`: fall back to the project file per command

A small helper keeps the pattern uniform:

```python
def _fallback(cli_value, project_value, default=""):
    """CLI flag wins, else the graider.toml value, else default."""
    return cli_value if cli_value not in (None, "") else (project_value or default)
```

Change each command's project-derived options to default `None` (or keep `""`)
and resolve via the project file. For **`setup`**:

```python
    config = _config(ctx)
    pf = config.project
    org = _fallback(org, pf.org if pf else "")
    template = template or (TemplateName(pf.template) if pf and pf.template else TemplateName.PYTHON)
    course = _fallback(course, pf.course if pf else "", "course")
    criteria_repo = _fallback(criteria_repo, pf.criteria_repo if pf else "")
    criteria_path = _fallback(criteria_path, pf.criteria_path if pf else "")
    name_prefix = _fallback(name_prefix, pf.name_prefix if pf else "")
    brief_url = _fallback(brief_url, pf.brief_url if pf else "")
    roster = roster or (pf.path(pf.roster) if pf and pf.roster else None)
    if roster is None:
        raise GraiderError("No roster: pass --roster or set roster in graider.toml")
    state_path = state_path or (pf.path(pf.state) if pf and pf.state else Path("graider.lock.json"))
```

> Make `--roster` optional (`Optional[Path] = typer.Option(None, ...)`) now that
> `graider.toml` can supply it; validate presence in the body. Do the same
> resolution for `review` (`--criteria-repo/path`, `--repo`) and `report`
> (`--state`). Keep it mechanical and identical across commands.

---

## Step 4 — `graider init`

```python
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
        f'roster = "students.xlsx"\n'
        f'state = "graider.lock.json"\n\n'
        f'[criteria]\nrepo = ""\npath = ""\n',
        encoding="utf-8",
    )
    print_success(f"Wrote {path} — edit it, then run `graider setup` with no flags.")
```

---

## Step 5 — Tests

`tests/test_config.py` additions:

- `find_project_file` finds `graider.toml` in the start dir and in a parent.
- Precedence: CLI `gitlab_url` beats `graider.toml`; `graider.toml` beats the
  global config file; global beats default.
- `ProjectFile.path()` resolves relative to the config dir, returns `None` for
  empty values.
- `resolve_config(project_start=tmp_path)` attaches the parsed `ProjectFile`.

`tests/test_cli.py` additions:

- Write a `graider.toml` + `roster.csv` in `tmp_path`; run `setup --dry-run` with
  no `--org`/`--roster` and `--config` pointed at a temp dir, using
  `monkeypatch.chdir(tmp_path)` so discovery finds the file; assert the preview
  uses the roster and does not error on the missing flags.
- `graider init` writes `graider.toml`; re-running without `--force` errors.

> The CLI tests must `monkeypatch.chdir()` into the temp dir (discovery walks up
> from cwd). Alternatively thread a hidden `--project-dir` for tests — but chdir
> keeps the production path honest.

---

## Step 6 — Verify

```sh
uv sync
uv run ruff check . && uv run ruff format --check . && uv run ty check
uv run pytest -q

mkdir -p /tmp/course && cd /tmp/course
uv run --project /home/sandro/work/grAIder graider init --org swe/2026 --course swe25
printf 'email,group\na@x.edu,1\n' > students.xlsx.csv && mv students.xlsx.csv students.csv
# edit graider.toml roster = "students.csv", then:
uv run --project /home/sandro/work/grAIder graider setup --dry-run   # picks up org+roster from graider.toml
```

---

## Notes for E2

- **E2 (multi-class)** generalizes `graider.toml` into named `[class.<name>]`
  sections + a `default_class`, and adds a global `--class` option. Build E1's
  single-context discovery/merge first; E2 layers class selection on top of the
  same `ProjectFile` resolution (select the class, then resolve fields within it).
```
