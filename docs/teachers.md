# Teachers Manual

Welcome to the Teachers Manual for grAIder.

grAIder simplifies the administrative overhead of dealing with hundreds of student repositories and grading complex software engineering projects.

## Setup and Config

grAIder uses the `~/.config/graider/config.toml` for defaults or accepts environment variables:
- `GITLAB_URL` (default: `https://gitlab.com`)
- `GITLAB_TOKEN` (your personal access token with `api` scope)

## Core Commands

- **`graider setup`**: (Coming Soon) Set up the GitLab environment based on a student roster (CSV/JSON), creating repositories and setting correct permissions.
- **`graider grade`**: (Coming Soon) Run static analysis like `qlty`, `pytest`, and coverage tools across student projects.
- **`graider review`**: (Coming Soon) Use agentic AI against the course criteria to automatically evaluate the project designs and code.
- **`graider report`**: (Coming Soon) Aggregate the metrics and AI feedback into a digestible report for final grading.

## Test Data
You can test the current test suite locally against the swegl-fs26 projects which are symlinked under `tests/fixtures/student_projects`.
