# grAIder — Implementation Plan

A CLI that sets up GitLab projects for student coursework groups and later grades
them using qlty metrics, tests/coverage, and an agentic AI evaluation against
course criteria.

## Big picture

```
graider
├── setup     # roster in → GitLab projects out (starter code, qlty, members invited)
├── criteria  # teacher: scaffold/author grading criteria from a syllabus (agentic)
├── grade     # qlty + tests + coverage → metrics report
├── review    # agentic AI grading against course criteria → report
└── report    # aggregate/export results (markdown, CSV)
```

Two audiences, one tool:

- **Teachers** run `setup`/`criteria` and grade *all* projects from the roster
  and state file.
- **Students** run `grade`/`review` inside their own clone to self-assess.
  This works because every starter repo ships a `.graider.yml` pointing at the
  grading criteria — no roster or state file needed.

Everything is driven by these inputs:

- **Roster** (CSV/Excel): student emails + group numbers.
- **Criteria repo** (GitLab repo + path): Markdown/AsciiDoc with the project
  brief and the coursework topics to evaluate, as an **ordered list of items**
  with stable IDs — the order is what makes staggered evaluation possible.
- **`.graider.yml`** (committed in each student repo): criteria repo/path,
  template language, course id. The per-repo entry point for self-assessment.
- **State file** (`graider.lock.json`, committed by the instructor): created
  project URLs, group ↔ project mapping, invite results. Makes every command
  idempotent and re-runnable.

## Tech choices

| Concern | Choice | Why |
|---|---|---|
| CLI framework | Typer + Rich | Declarative subcommands, good `--help`, nice tables/progress output |
| GitLab API | python-gitlab | Mature, works against gitlab.com and self-hosted via `--gitlab-url` |
| Roster parsing | openpyxl + stdlib csv | Excel and CSV without pulling in pandas |
| Models/config | Pydantic v2 | Validated roster rows, config, and state file schema |
| Templates | Embedded in package (`src/graider/templates/`) | No network dependency; rendered with string substitution |
| Code quality | qlty CLI via subprocess | `qlty check` / `qlty smells` with `--json` output |
| Agentic grading | Claude Agent SDK | Skills-based evaluation; criteria + qlty results as context |

## Milestone 1 — CLI skeleton, config, auth

- Typer app with `setup`, `grade`, `review`, `report` stubs; `--version`, global
  `--gitlab-url` (default `https://gitlab.com`) and `--dry-run` options.
- Token resolution order: `--token` flag → `GITLAB_TOKEN` env var → config file
  (`~/.config/graider/config.toml`).
- **Missing token UX**: print the exact URL to create one, derived from the
  instance URL: `<gitlab-url>/-/user_settings/personal_access_tokens`
  (scopes: `api`), and exit with a clear message.
- Rich-based output helpers (status tables, error formatting).

Deliverable: `graider --help` works; `graider setup` without a token prints the
token link.

## Milestone 2 — Roster parsing

- `roster.py`: read `.csv` and `.xlsx` into `list[Student]`
  (`email`, `group_number`; tolerate extra columns, header aliases like
  "E-Mail"/"Group"/"Team").
- Validation with clear line-level errors: bad emails, missing group numbers,
  duplicate students.
- Group aggregation: `dict[group_number, list[Student]]`.

Deliverable: `graider setup --roster students.xlsx --dry-run` prints the parsed
groups as a table without touching GitLab.

## Milestone 3 — GitLab client layer

- Thin wrapper around python-gitlab: resolve target group/org (by path, from
  `--org`), create project, look up users by email, invite members
  (developer role), protect default branch.
- **Invite reporting**: for each student, one of `invited` / `already member` /
  `no account found` — collected and shown as a summary table, and recorded in
  the state file so instructors can chase missing accounts.
- Retry/rate-limit handling; all mutations gated behind `--dry-run`.

Deliverable: unit-tested client with mocked API; manual smoke test against a
sandbox group.

## Milestone 4 — Starter templates + qlty setup

- Embedded starters, one per language, selected via `--template {python,java,cpp}`:
  - **python**: uv layout (`pyproject.toml`, `src/`, `tests/`, pytest, ruff)
  - **java**: Gradle (`build.gradle.kts`, wrapper, JUnit 5)
  - **cpp**: CMake (`CMakeLists.txt`, Catch2 or GoogleTest, `src/`, `test/`)
- Each starter includes: README with the project brief link, `.gitignore`,
  a `qlty.toml` tuned for the language, a minimal GitLab CI that runs
  tests + qlty on push, and a **`.graider.yml`**:

  ```yaml
  course: swe25
  template: python
  criteria:
    repo: https://gitlab.example.com/swe/criteria
    path: swe25/
  ```

  This is what lets students run `graider grade` / `graider review` in their
  own clone for self-assessment — the tool finds everything it needs in the
  repo itself.
- Push as initial commit via python-gitlab commit API (no local git needed).

Deliverable: `graider setup ... --template python` creates a ready-to-clone repo
with passing CI.

## Milestone 5 — Full `setup` orchestration

- **Random project names**: adjective–noun pairs (e.g. `brave-otter`), collision
  check against existing projects in the org, `--name-prefix` for course tags
  (e.g. `swe25-brave-otter`).
- Flow per group: create project → push starter → set up qlty → invite members.
- Write/update the **state file** with project URLs, names, members, invite
  status. Re-running `setup` skips existing projects and only fixes gaps
  (missing members, missing starter) — idempotent by design.
- Final summary: table of groups, project URLs, invited/missing students.

Deliverable: end-to-end `setup` on a test roster; `projects` URL file usable by
the grading commands.

## Milestone 6 — Grading harness (`grade`)

- Two modes, auto-detected:
  - **Teacher mode**: state file present → clone/pull all projects from it
    into a workspace dir and grade each one.
  - **Student mode**: no state file but a `.graider.yml` in the current repo →
    grade just this repo in place. Same output format, single project.
- Per project, run and parse:
  - `qlty check --format json` and `qlty smells --format json`
  - language-appropriate tests + coverage (pytest --cov / gradle test +
    jacoco / ctest + gcovr), detected from the template recorded at setup.
- Normalize into a `GradeResult` model per group: issue counts by severity,
  smell counts, test pass/fail, coverage %.
- Store raw tool output alongside the parsed results (`results/<project>/`).

Deliverable: `graider grade` produces a metrics table across all groups and a
JSON results file.

## Milestone 7 — Criteria loading & staggered evaluation

- `criteria.py`: fetch the criteria document(s) from a GitLab repo + path
  (from `--criteria-repo`/`--criteria-path`, or from `.graider.yml` in student
  mode), supporting Markdown and AsciiDoc.
- **Criteria format convention**: the evaluation criteria are an ordered list
  of items with stable IDs (numbered headings, e.g. `## 3. Testing`, or an
  explicit `id:` attribute). Parse into `list[CriteriaItem]` preserving order;
  the project brief stays free-form text.
- **Staggered evaluation**: students haven't seen every topic yet, so
  evaluation can be cut off at any point in the item order:
  - `graider review --up-to 5` (or an item ID like `--up-to testing`)
    evaluates only items 1–5.
  - The criteria repo can declare the current default in a small
    `graider-criteria.yml` next to the documents (`released_up_to: 5`), so the
    teacher advances the cutoff once per semester week and student
    self-assessment automatically follows — no flag needed.
  - Precedence: `--up-to` flag → `released_up_to` in criteria repo → all items.
- Items beyond the cutoff are listed in the report as "not yet evaluated"
  rather than silently dropped.

Deliverable: `graider review --dry-run` shows the loaded items, their order,
and which are in/out of scope for the current cutoff.

## Milestone 8 — Agentic review (`review`)

- Claude Agent SDK agent per project with **skills**:
  - *criteria-evaluation*: does the code address the brief and covered topics?
  - *code-quality*: interpret qlty results + spot issues qlty can't
    (design, naming, cohesion) — general quality per qlty.sh philosophy.
  - *test-quality*: are the tests meaningful, not just coverage-chasing?
- Inputs per run: criteria text **truncated at the staggered-eval cutoff**
  (Milestone 7), qlty/test results from Milestone 6, and read-only access to
  the cloned repo. Works in teacher mode (all projects) and student mode
  (current repo, self-assessment).
- Output: structured verdict (Pydantic schema — per-criterion score, evidence
  with file:line references, overall summary) so grading is auditable.
- Cost controls: `--model`, `--max-turns`, per-project token budget, and
  caching so re-runs only review changed projects (compare HEAD SHA in state
  file).

Deliverable: `graider review` writes a per-group AI evaluation next to the
metrics results.

## Milestone 9 — Teacher skill: criteria authoring (`criteria`)

- `graider criteria init --syllabus syllabus.pdf --out swe25/`: an agentic
  skill for teachers that drafts the grading criteria from their course
  material:
  - reads the syllabus (PDF/Markdown/AsciiDoc), extracts the covered topics in
    teaching order, and generates a criteria document in the ordered-items
    format from Milestone 7 (stable IDs, one item per topic, suggested
    evaluation questions per item);
  - scaffolds the criteria repo layout: project brief stub, criteria doc,
    `graider-criteria.yml` with `released_up_to: 0`.
- `graider criteria check`: validates an existing criteria repo (item order,
  unique IDs, cutoff file) so teachers get fast feedback before students hit a
  parse error.
- A companion *setup-assistant* skill walks teachers through the whole flow
  interactively: roster format, org choice, template choice, criteria repo —
  useful for first-time users who'd otherwise read docs.

Deliverable: from a syllabus PDF to a valid, staggered-eval-ready criteria
repo in one command, plus review by the teacher.

## Milestone 10 — Reports & polish

- `graider report`: merge metrics + AI review into per-group Markdown reports
  and one instructor CSV (group, project URL, coverage, issues, AI scores).
- Docs: README quickstart, example roster, example criteria repo layout.
- Hardening: integration test against a local GitLab (docker) or recorded API
  fixtures; `graider --version`; publish to the GitLab package registry via the
  existing CI pipeline.

## Suggested package layout

```
src/graider/
├── cli.py            # Typer app, subcommands
├── config.py         # token/url resolution, config file
├── roster.py         # CSV/Excel parsing → Student/Group models
├── models.py         # Pydantic: Student, Group, ProjectState, GradeResult
├── gitlab_client.py  # python-gitlab wrapper
├── names.py          # random project names
├── state.py          # graider.lock.json read/write
├── templates/        # python/, java/, cpp/ starters + qlty.toml per language
├── grading/
│   ├── runner.py     # clone, run qlty + tests, parse output
│   └── coverage.py   # per-language coverage extraction
├── criteria.py       # fetch + parse criteria repo, staggered-eval cutoff
├── project_config.py # .graider.yml read/write (student-mode entry point)
├── review/
│   ├── agent.py      # Claude Agent SDK setup
│   └── skills/       # criteria-evaluation, code-quality, test-quality
└── authoring/
    └── skills/       # syllabus→criteria drafting, setup assistant (teacher)
```

## Order of attack

Milestones 1–5 form the **setup half** and are independently useful — that's
the first release. 6–7 are pure plumbing with no AI risk and unlock student
self-assessment (`.graider.yml` + staggered cutoff). 8 is the experimental
part; keeping it behind its own `review` command means metrics-based grading
(6) works even if the AI half is still being tuned. 9 (teacher authoring) is
independent of 6–8 and can be pulled forward if criteria need to exist before
the first `setup` run — which in practice they do, so expect to build a
minimal version of `criteria init` alongside Milestone 4.
