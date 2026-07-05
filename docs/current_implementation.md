# Current Implementation

grAIder is a fully featured CLI tool. This page outlines the currently implemented components, commands, configuration rules, and testing tools.

## Command Line Interface (CLI)

Built on Typer, `graider` exposes several subcommands and tool groups:

### Core Commands

*   **`graider init`**: Scaffolds a `graider.toml` configuration file in the current directory, capturing the course context (default GitLab organization, templates, course metadata, roster paths, and criteria).
*   **`graider setup`**: Reads `graider.toml` (and optional class configurations via `--class`) to provision GitLab projects for student groups found in a roster file. For each group:
    *   Creates a private repository.
    *   Pushes the selected starter template (`python`, `java`, `cpp`, `go`, `rust`, or `typescript`).
    *   Protects the `main` branch.
    *   Invites group members with their respective roles.
    *   Supports running with `--dry-run` to preview the groups and names locally without modifying GitLab.
*   **`graider grade`**: Runs code quality checkers, unit tests, and coverage tools on student repositories.
    *   Uses `--repo` (default: `.`) to grade a single repository (student self-assessment).
    *   Uses `--workspace <dir>` to automatically find and grade all subdirectories containing a `.graider.yml` configuration (teacher grading).
    *   Saves outputs to `grade-results.json`.
*   **`graider review`**: Uses an LLM to draft an AI review of the codebase against specific, staggered criteria. The review is written locally to `review-results.json` as a **draft** — nothing is posted until a teacher publishes it.
    *   Accepts `--criteria-dir` (or fetches criteria from GitLab using `--criteria-repo` and `--criteria-path`).
    *   Uses `--up-to <cutoff>` to evaluate only criteria up to a certain milestone (represented by position or item ID), falling back to the `released_up_to` value in the criteria directory's `graider-criteria.yml`.
    *   Supports `--backend auto|api|claude-code|openai|gemini|glm`, where `claude-code` relies on a Claude Pro/Max subscription via the Claude Code CLI and the others use their respective provider API keys.
    *   Caches results by content hash so unchanged repositories are skipped on re-runs; bypass with `--force`/`--no-cache`. `--formative` produces a gentler self-check review.
*   **`graider review publish`**: Lets a teacher approve (or edit/skip) the drafted feedback and post it back to GitLab via `--feedback mr|issue` — as a Merge Request note or an Issue.
*   **`graider report`**: Merges functional grading (`grade-results.json`) and AI reviews (`review-results.json`) into digestible per-project Markdown reports and generates a consolidated `summary.csv` for course-wide grading.
*   **`graider interview`**: Generates oral-exam (viva) questions that probe whether a student understands their own project and how it connects to the curriculum. Works on a single topic or several (`--topic`, repeatable; omit for all), takes an optional `--prompt` to steer the questions, and writes a Markdown file where each question is followed by the key points a correct answer should cover and red flags to watch for. Shares the `--backend auto|api|claude-code` model plumbing with `review`.

### Auxiliary Commands

*   **`graider criteria init --syllabus FILE --out DIR`**: Automatically drafts structured grading criteria from a syllabus file using Claude.
*   **`graider criteria check DIR`**: Validates a criteria directory (checks for correct IDs, numeric order, and valid cutoffs).
*   **`graider template list`**: Lists available starter templates (`python`, `java`, `cpp`, `go`, `rust`, `typescript`).
*   **`graider template render`**: Performs offline rendering of a starter template with placeholder substitution (`{{project_name}}`, `{{course}}`, etc.) to a local directory.
*   **`graider skills install`**: Installs the grAIder Agent Skill into `~/.claude/skills` (or a project directory via `--project`) so that the Claude Code CLI can automatically invoke and run grAIder.

## Configuration Resolution

grAIder resolves settings by merging values from multiple sources in the following precedence order:

1.  **Command Line Flags**: E.g., `--gitlab-url`, `--token`, `--class`, `--dry-run`.
2.  **Environment Variables**: `GITLAB_URL`, `GITLAB_TOKEN`.
3.  **Local Context TOML**: `graider.toml` located in the current working directory.
4.  **Global TOML**: Config file located at `~/.config/graider/config.toml`.

## Roster Parsing

grAIder parses rosters in CSV (`.csv`) and Excel (`.xlsx`, `.xlsm`) formats. It normalizes headers (matching e.g., `E-Mail`/`Mail` or `Group`/`Team`), aggregates members by group, validates emails, and reports parsing issues annotated with row numbers.

## GitLab Client Wrapper

A wrapper around `python-gitlab` handles:

*   Authentication and namespace discovery.
*   Repository creation, file commit (template rendering), branch protection, and member invitations.
*   Case-insensitive public email matching to locate GitLab users.
*   Automatic rate-limit handling and retries for transient HTTP errors.
*   Fully offline execution when `--dry-run` is active.

## Starter Templates

Boilerplate configurations for various language toolchains:

*   **`python`**: Powered by `uv`, `pytest`, and `ruff`.
*   **`java`**: Powered by Gradle and JUnit 5.
*   **`cpp`**: Powered by CMake and Catch2.
*   **`go`**: Standard `go` toolchain with `go test`.
*   **`rust`**: Cargo with `nextest`.
*   **`typescript`**: Node/npm project with a test runner.

Templates are stored using `.tmpl` + `dot_` storage schemes in the source tree to prevent conflicts, and dynamically render configuration files (e.g., `.gitlab-ci.yml`, `.graider.yml`).
