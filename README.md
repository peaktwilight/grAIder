# grAIder

## Development

Managed with [uv](https://docs.astral.sh/uv/), linted/formatted with
[ruff](https://docs.astral.sh/ruff/), type-checked with [ty](https://docs.astral.sh/ty/).

```sh
uv sync                     # install dependencies (incl. dev tools)
uv run graider              # run the CLI
uv run pytest               # run tests
uv run ruff check .         # lint
uv run ruff format .        # format
uv run ty check             # type check
```

## CI/CD

GitLab CI (`.gitlab-ci.yml`) runs on merge requests, the default branch, and tags:

- **lint** — ruff lint (reported as code quality in MRs), ruff format check, ty
- **test** — pytest with JUnit report shown in MRs
- **build** — `uv build` (sdist + wheel as artifacts)
- **publish** — on `vX.Y.Z` tags, publishes to the project's GitLab PyPI package registry
