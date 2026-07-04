# Feature Requests — Implementation Plan

Design plan for the post-roadmap features gathered in `feature_requests.md`.
These come **after** Milestones 1–10 (the core setup/grade/review pipeline) and
build on that foundation — several depend on Milestone 8's agentic review being
in place. Numbered here as extension milestones **E1–E4**.

Unlike the M1–M7 specs, this is a design plan (interfaces + approach + risks),
not line-by-line copy-paste code, because these features touch external
workflows (GitLab MRs/issues) and cross-cut existing modules.

---

## E1 — Context-aware configuration

> "Configuration stored within a coursework project directory, so running
> `graider` from inside a project folder auto-fetches the relevant repos and
> docs based on the current context."

### Goal
Running any `graider` command from inside (or under) a course/project directory
picks up that context automatically — no repeated `--org`/`--roster`/
`--criteria-*`/`--state` flags.

### Approach
- Introduce a **project-level config file**, `graider.toml`, discovered by
  walking up from the cwd (like git finding `.git/`). It records the durable
  context for a course working directory:

  ```toml
  gitlab_url = "https://gitlab.com"
  org = "swe/2026"
  roster = "students.xlsx"
  template = "python"
  state = "graider.lock.json"

  [criteria]
  repo = "https://gitlab.com/swe/criteria"
  path = "swe25/"
  ```

- Extend `config.py`: add `find_project_config(start: Path) -> Path | None`
  (upward walk) and fold its values into `resolve_config`, keeping the existing
  precedence and inserting the project file **below** CLI/env and **above** the
  global `~/.config/graider/config.toml`.
- Extend `Config` (and the command signatures) so `--org`, `--roster`,
  `--criteria-repo/path`, `--template`, `--state` all fall back to the project
  file. A command run with no flags in a configured directory "just works".
- `graider init` (new): scaffold a `graider.toml` in the current directory
  interactively (or from flags), so instructors set context once.

### Key files
`config.py` (discovery + merge), `models.py` (a `ProjectConfig` model), `cli.py`
(new `init`, thread fallbacks into `setup`/`grade`/`review`).

### Risks / notes
- Precedence must be explicit and documented (CLI > env > project `graider.toml`
  > global config > default). Add tests per layer, mirroring the Milestone 1
  config tests.
- Don't confuse `graider.toml` (instructor context, this feature) with
  `.graider.yml` (per-student-repo self-assessment pointer, Milestone 4).

---

## E2 — Multiple class support

> "A CLI flag to select which class to operate on; default to the first
> available class."

### Goal
Manage several courses from one machine/config without re-specifying everything.

### Approach
- Generalize the E1 project config into a multi-class config: named class
  sections, plus a default.

  ```toml
  default_class = "swe25"

  [class.swe25]
  org = "swe/2026"
  roster = "swe25/students.xlsx"
  state = "swe25/graider.lock.json"
  criteria = { repo = "...", path = "swe25/" }

  [class.dbs25]
  org = "dbs/2026"
  roster = "dbs25/students.xlsx"
  state = "dbs25/graider.lock.json"
  ```

- Add a global `--class <name>` option (on the app callback). Resolution:
  `--class` → `default_class` → the single class if only one is defined → error
  ("multiple classes; pass --class") if ambiguous.
- All context lookups (org/roster/criteria/state) resolve *within the selected
  class* before falling back to top-level/global values.

### Key files
`config.py` (class selection layered on E1), `cli.py` (`--class` global option),
`models.py` (`ClassConfig`, `MultiClassConfig`).

### Risks / notes
- Depends on E1 (shared config-file plumbing) — build E1 first.
- "Default to first available" is only safe when exactly one class exists;
  when several exist and no `default_class`/`--class` is given, fail clearly
  rather than guessing.

---

## E3 — Feedback via merge requests

> "Students open a merge request; the AI review is posted as comments on that MR."

### Goal
Turn a Milestone 8 review into inline/summary comments on a student's MR.

### Approach
- New `graider review --mr <iid>` (or auto-detect the open MR for the current
  branch/project). After running the agentic review (Milestone 8), map each
  finding to a comment:
  - **Inline** comments on `file:line` where the finding has a location, using
    the MR diff position (GitLab discussions API on the MR).
  - A **summary** comment with the per-criterion verdict table and the overall
    result.
- Extend `GitLabClient` with:
  - `get_open_merge_request(project_id, source_branch) -> mr` / `list_merge_requests`.
  - `post_mr_note(project_id, mr_iid, body)` (summary).
  - `post_mr_discussion(project_id, mr_iid, body, position)` (inline; needs the
    diff `base_sha/head_sha/start_sha` + new_path + new_line).
- Idempotency: tag grAIder-authored notes (e.g. a hidden `<!-- graider:review -->`
  marker) so re-running updates/replaces prior feedback instead of piling on.
- Honor `--dry-run`: render the comments locally without posting.

### Key files
`gitlab_client.py` (MR notes/discussions), a `feedback/mr.py` mapping
review → comments, `cli.py` (`review --mr`).

### Risks / notes
- **Depends on Milestone 8** (there is no review output to post until then).
- Inline positioning via the GitLab discussions API is fiddly (needs exact diff
  SHAs); fall back to a summary note when a precise position can't be computed.
- Requires the review's findings to carry `file`/`line` (ensure Milestone 8's
  output schema includes them).

---

## E4 — Feedback through issues

> "For students committing directly to `main`, generate feedback as an issue."

### Goal
A no-MR workflow: post the review as a GitLab **issue** on the student project.

### Approach
- New `graider review --as-issue`. Run the review, then create/update one issue
  per project titled e.g. `grAIder feedback — <criteria cutoff>`, body = the
  summary verdict + a checklist of per-criterion results (unchecked items = not
  yet met), so students can track remediation.
- Extend `GitLabClient`:
  - `find_issue_by_title(project_id, title)` / `create_issue(project_id, title, body)`
    / `update_issue(project_id, issue_iid, body)`.
- Idempotency: reuse the same titled issue (or the `<!-- graider:review -->`
  marker) across re-runs; update the body rather than opening duplicates.
- `--dry-run` renders the issue body locally without posting.

### Key files
`gitlab_client.py` (issues), `feedback/issue.py` (review → issue body), `cli.py`
(`review --as-issue`).

### Risks / notes
- **Depends on Milestone 8.** Shares the review→markdown rendering with E3;
  factor a common `feedback/render.py` producing the summary table + checklist
  so MR and issue paths reuse it.
- Let the instructor choose the channel (`--mr` vs `--as-issue`) or auto-pick
  based on whether an open MR exists for the branch.

---

## Suggested order

1. **E1** (project config discovery) — foundational; removes flag repetition.
2. **E2** (multi-class) — layers on E1's config plumbing.
3. **Milestone 8** must land before E3/E4 (they post its output).
4. **E3 / E4** — build the shared `feedback/render.py` first, then the MR path
   (E3) and issue path (E4) on top; they differ only in the GitLab surface they
   post to.

## Cross-cutting

- All four honor the existing offline `--dry-run` contract: no network,
  render/preview only.
- All GitLab writes go through `GitLabClient` (consistent error wrapping,
  retries, dry-run gating) — do not call `python-gitlab` directly from the
  feedback modules.
- Feedback idempotency uses a hidden marker comment so re-runs update rather
  than duplicate — the same discipline as the `graider.lock.json` state file.
