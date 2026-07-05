# grAIder

**AI-powered coursework provisioning and grading for GitLab.**

grAIder is a command-line tool that manages the full lifecycle of a programming
course on GitLab: it provisions per-group repositories from starter templates,
runs unified quality/test/coverage grading, drafts staggered AI reviews against
a rubric, generates oral-exam (viva) questions grounded in each student's own
project, and consolidates everything into per-group reports and a class CSV.

Students use the **same** tool locally to self-assess before they submit.

> **Status:** `0.1.0` · Python **3.13+** · [Full documentation →](https://peaktwilight.github.io/grAIder/)

---

## Highlights

- **Automated GitLab provisioning** — create a private repo per group, push a
  starter template, protect `main`, and invite members from a CSV/XLSX roster,
  all from one command (with `--dry-run` to preview).
- **Unified grading** — run code-quality checks, the test suite, and coverage in
  one pass. `graider grade --repo .` for a student; `--workspace <dir>` grades a
  whole class.
- **Staggered AI review** — grade incrementally against milestone criteria
  (`--up-to`) using Claude, OpenAI, Gemini, or GLM. Reviews are drafted locally,
  then a teacher **approves and publishes** them to a Merge Request or Issue.
- **Interview / viva questions** — generate oral-exam questions grounded in a
  student's own code, each with the key points a correct answer must cover and
  red flags that betray a shaky understanding.
- **Calibration** — anchor the model to teacher-graded exemplars and measure
  agreement so AI verdicts track your grading.
- **Cost & caching** — per-run token-usage and cost estimates; a content-hash
  cache skips unchanged repositories on re-runs.
- **Six starter languages** — Python, Java, C++, Go, Rust, and TypeScript.
- **Integrity signals** — neutral commit-history metrics (cadence, contribution
  split, largest commit) and prompt-injection detection surfaced for triage —
  never used as an automatic penalty.

## Installation

grAIder is a Python 3.13+ package managed with [uv](https://docs.astral.sh/uv/).

```sh
# From source (development)
git clone https://github.com/peaktwilight/grAIder.git
cd grAIder
uv sync                       # install with dev tools
uv run graider --help

# As a tool
uv tool install graider                 # core (Anthropic + Claude Code backends)
uv tool install "graider[openai]"       # add OpenAI / GLM backends
uv tool install "graider[google]"       # add Google Gemini backend
```

## Quickstart

### Teachers

```sh
# 1. Scaffold a course config (graider.toml) in the current directory
graider init --org my-course-group --template python --course swe-2026

# 2. Draft grading criteria from a syllabus (AI-assisted), then validate
graider criteria init --syllabus syllabus.pdf --out criteria/
graider criteria check criteria/

# 3. Provision GitLab repos for every group in the roster (preview first)
graider setup --roster roster.xlsx --dry-run
graider setup --roster roster.xlsx

# 4. Grade every provisioned repo, then draft AI reviews up to a milestone
graider grade --workspace ./submissions
graider review --workspace ./submissions --criteria-dir criteria/ --up-to m2

# 5. Approve and post the reviews to GitLab, then build reports
graider review publish --feedback mr
graider report --workspace ./submissions --out-dir reports/
```

### Students

Your provisioned repo contains a `.graider.yml`. From its root:

```sh
graider grade            # quality + tests + coverage, exactly like the teacher runs
graider review           # local AI self-review against the released criteria
graider skills install   # optional: let the Claude Code CLI drive grAIder for you
```

## Commands

| Command | What it does |
| --- | --- |
| `graider init` | Scaffold a `graider.toml` course config. |
| `graider setup` | Create a GitLab project per group and invite members from a roster. |
| `graider grade` | Run quality checks, tests, and coverage on a repo (`--repo`) or a whole workspace (`--workspace`). |
| `graider review` | Draft an AI review against staggered criteria (writes `review-results.json`; nothing posted yet). |
| `graider review publish` | Teacher approves the draft and posts it to GitLab (`--feedback mr\|issue`). |
| `graider calibrate` | Record a teacher-graded exemplar and measure model agreement (`--check`). |
| `graider interview` | Generate viva questions grounded in the student's project. |
| `graider report` | Merge grades + reviews into per-project reports and a `summary.csv`. |
| `graider criteria init` | Draft a staggered-eval criteria repo from a syllabus. |
| `graider criteria check` | Validate a criteria directory (IDs, order, cutoffs). |
| `graider template list` / `render` | List or offline-render a starter template. |
| `graider skills install` | Install the grAIder Agent Skill for the Claude Code CLI. |

Run `graider <command> --help` for the full flag set. Global options apply
before any subcommand: `--gitlab-url` (`GITLAB_URL`), `--token` (`GITLAB_TOKEN`),
`--config`, `--class`, and `--dry-run`.

## AI backends

The AI commands (`review`, `interview`, `criteria init`, `calibrate`) run through
a shared model abstraction, selected with `--backend`:

| Backend | Provider | Credentials |
| --- | --- | --- |
| `api` | Anthropic API | `ANTHROPIC_API_KEY` |
| `claude-code` | Claude Code CLI (Pro/Max subscription) | `claude login` |
| `openai` | OpenAI / OpenAI-compatible | `OPENAI_API_KEY`, opt. `OPENAI_BASE_URL` |
| `glm` | GLM / Zhipu (BigModel) | `GLM_API_KEY` / `ZHIPUAI_API_KEY` |
| `gemini` | Google Gemini | `GEMINI_API_KEY` / `GOOGLE_API_KEY` |
| `auto` *(default)* | Claude Code if the `claude` binary is on `PATH` and no `ANTHROPIC_API_KEY` is set, otherwise the Anthropic API. |

`openai`, `glm`, and `gemini` are text-only (no PDF syllabi) and require the
`graider[openai]` or `graider[google]` extra. The default model is
`claude-opus-4-8`; override per run with `--model`.

## Starter templates

`python` · `java` · `cpp` · `go` · `rust` · `typescript`. Each ships a working
project plus a rendered `.graider.yml`, `.gitlab-ci.yml`, `qlty.toml`, and a
reflection prompt. Templates are stored as `.tmpl` / `dot_` files and rendered
with placeholder substitution (`{{project_name}}`, `{{course}}`, …).

## Configuration

Settings are resolved in precedence order:

1. **CLI flags** (`--gitlab-url`, `--token`, `--class`, `--dry-run`, …)
2. **Environment variables** (`GITLAB_URL`, `GITLAB_TOKEN`, provider API keys)
3. **Local `graider.toml`** in the working directory (supports `[class.<name>]` sections)
4. **Global `~/.config/graider/config.toml`**

Rosters are read from `.csv`, `.xlsx`, and `.xlsm` files with fuzzy header
matching (email / group / name), per-row validation, and duplicate detection.

## Documentation

Full guides live in [`docs/`](docs/) and are published to GitHub Pages:

- **[Teachers Manual](docs/teachers.md)** — setup → criteria → provisioning → grading → review → reporting.
- **[Students Manual](docs/students.md)** — local grading, self-review, and Agent Skill setup.
- **[Current Implementation](docs/current_implementation.md)** — technical reference for commands, config, and integrations.
- **[Learning Science](docs/learning_science.md)** & **[Topic Guides](docs/topic_guides.md)** — the pedagogy behind the rubric.

## Development

Managed with [uv](https://docs.astral.sh/uv/), linted/formatted with
[ruff](https://docs.astral.sh/ruff/), and type-checked with
[ty](https://docs.astral.sh/ty/).

```sh
uv sync                     # install dependencies (incl. dev tools)
uv run graider              # run the CLI
uv run pytest               # run tests
uv run ruff check .         # lint
uv run ruff format .        # format
uv run ty check             # type check
uv run mkdocs serve         # preview the docs site locally
```

## CI/CD

GitHub Actions runs on pushes to `main`, pull requests, and version tags:

- **CI** (`ci.yml`) — ruff lint, ruff format check, `ty`, and pytest.
- **Docs** (`docs.yml`) — builds the MkDocs site and deploys it to GitHub Pages.
- **Publish** (`publish.yml`) — on `vX.Y.Z` tags, builds and publishes to PyPI
  via Trusted Publishing (OIDC, no stored token).

> Note: the `.gitlab-ci.yml` shipped inside the starter templates is separate —
> it runs in each **student's** provisioned GitLab repository, not for this tool.
