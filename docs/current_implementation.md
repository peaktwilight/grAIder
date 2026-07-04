# Current Implementation

As of the current version, grAIder implements the following components:

## Command Line Interface (CLI)
Built on Typer, `graider` serves as the entrypoint. 
- The `setup` subcommand accepts a `--roster` spreadsheet option and performs roster parsing, validation, and group aggregation. In `--dry-run` mode, it prints a Rich table of the groups and members.
- The `template` command group has subcommands `list` (lists available templates: `python`, `java`, `cpp`) and `render` (offline rendering of templates with placeholder substitution to a local directory).
- The `grade`, `review`, and `report` subcommands remain as stubs.

## Configuration Resolution
Configuration logic in `config.py` correctly parses and merges arguments from:
1. Command Line Arguments (`--gitlab-url`, `--token`)
2. Environment Variables (`GITLAB_URL`, `GITLAB_TOKEN`)
3. Global TOML configuration file (`~/.config/graider/config.toml`)

## Shared Domain Models
Pydantic models in `models.py` define the core structure of the domain data, including:
- `Student` (with strict email, non-empty group, and clean name validation).
- `Group` (aggregating students).
- `InviteStatus`, `InviteResult`, `ProjectRef`, and `RenderedFile`.

## Roster Parsing
Implemented in `roster.py`:
- Parses CSV (`.csv`) and Excel (`.xlsx`, `.xlsm`) rosters.
- Normalizes and matches header aliases (e.g. `E-Mail`/`Mail`, `Group`/`Team`).
- Identifies and aggregates duplicate students, invalid emails, and empty group fields, reporting all errors prefixed with the spreadsheet row number.

## GitLab Client Wrapper
Implemented in `gitlab_client.py`:
- Wraps `python-gitlab` with automatic rate-limit handling and retries for transient errors.
- Exposes `authenticate`, `get_namespace_id`, `create_project`, `find_user_by_email` (case-insensitive public email matching), `invite_member` (returns `invited`, `already_member`, or `no_account`), `protect_branch`, and `commit_files` (pushing templates via the commit API).
- Supports fully offline, tokenless `--dry-run` execution.

## Starter Templates
- Bundled starter configurations for `python` (uv, pytest, ruff), `java` (gradle, junit 5), and `cpp` (cmake, Catch2) under `src/graider/templates/` using a `.tmpl` + `dot_` storage scheme to prevent interference with outer project tools.
- Includes a template engine that replaces `{{placeholder}}` values (e.g., `{{project_name}}`, `{{course}}`) and generates student repositories with ready-to-use CI pipelines.

## Test Framework
A fully mocked unit test suite (59 cases):
- `pytest` runs client, CLI, config, roster, and template suites with no network access.
- `ruff` (linter and formatter) and `ty` (type checker) checks run cleanly.

### Cross-language integration tests
`tests/integration/test_starters.py` renders each starter and actually builds and
tests it with the real toolchain (python: `uv sync` + ruff + pytest; java:
`gradle test`; cpp: `cmake` + `ctest` with a fetched Catch2). These carry the
`integration` marker and are **deselected by default**, so a plain
`uv run pytest` stays fast and offline. Run them explicitly with:

- `uv run pytest -m integration` — uses the toolchains installed on the host
  (each test skips if its toolchain is missing), or
- `scripts/check-starters.sh` — renders and builds every starter inside its CI
  Docker image, so only Docker is required on the host.

## Continuous Integration
`.gitlab-ci.yml` runs on merge requests, the default branch, and tags:
- **lint** — `ruff check` (as a code-quality report), `ruff format --check`, `ty`.
- **test** — unit `pytest` with a JUnit report.
- **starters** — `starter-python`, `starter-java`, and `starter-cpp` jobs each
  render and build the corresponding starter inside the matching language
  container (`uv` image, `gradle:8.7-jdk21`, `gcc:13`), proving the templates
  produce working projects across all languages.
- **build / publish** — `uv build`, and publish to the GitLab PyPI registry on
  `vX.Y.Z` tags.
- **deploy** — build and publish this documentation site via GitLab Pages.
