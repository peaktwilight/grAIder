# Current Implementation

As of the current version, grAIder implements the following components:

## Command Line Interface (CLI)
Built on Typer, `graider` serves as the entrypoint. The current subcommands (`setup`, `grade`, `review`, `report`) are **stubs**. They do not yet execute the logic over the network, but their signatures and help descriptions are defined.

## Configuration Resolution
Configuration logic in `config.py` correctly parses and merges arguments from:
1. Command Line Arguments (`--gitlab-url`, `--token`)
2. Environment Variables (`GITLAB_URL`, `GITLAB_TOKEN`)
3. Global TOML configuration file (`~/.config/graider/config.toml`)

## Test Framework setup
The test infrastructure has been prepared:
- `pytest`, `ruff`, and `ty` are used for tests, linting, and formatting.
- `conftest.py` has been populated with fixtures pointing to realistic coursework projects (`swegl-fs26`) and project briefs (`14-MP`).
- Placeholder tests are running and successfully finding the test data.

## Missing Tooling
- Actual integration with the `qlty` command-line tool.
- GitLab API interaction (creating repos from rosters, gathering MR metrics).
- Agentic AI implementation for automated review.
