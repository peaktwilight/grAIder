---
name: graider
description: Use the grAIder CLI to set up, grade, and review GitLab coursework projects. Invoke when the user wants to create student projects from a roster, grade repos, review against criteria, or author grading criteria.
---

# grAIder

grAIder is a CLI for managing GitLab coursework end to end: create one project
per group from a roster, grade with qlty + tests + coverage, review against
staggered criteria with AI, and export reports.

## Commands

- `graider init` — scaffold a `graider.toml` course context (org, roster,
  template, criteria). After this, most commands run with no flags.
- `graider setup` — create a project per group from the roster; push a starter,
  protect `main`, invite members. Records `graider.lock.json`.
- `graider grade` — qlty issues/smells + tests + coverage. `--repo .` (student
  self-check) or `--workspace DIR` (teacher, one subdir per repo).
- `graider review` — AI review against criteria; `--up-to <n|id>` for staggered
  evaluation. `--criteria-dir DIR` or a repo `.graider.yml`.
- `graider report` — merge grade + review into per-project Markdown + a
  `summary.csv` gradebook.
- `graider criteria init --syllabus FILE --out DIR` / `graider criteria check DIR`
  — draft criteria from a syllabus; validate a criteria repo.
- `graider template render|list` — inspect the python/java/cpp starters.

## What to look out for

- **Dry-run first.** `graider --dry-run setup` previews project names and members
  fully offline (no token, no writes). The global `--dry-run` goes **before** the
  subcommand; command flags go **after**.
- **`--org` is required for a real setup** unless it's in `graider.toml`. With a
  `graider.toml`, bare `graider setup` works inside the course directory.
- **`graider.lock.json` is committed and setup is idempotent** — re-running skips
  existing projects and only invites members not yet added. Don't delete it.
- **`no_account` in the invite summary means "verify manually," not "no account."**
  GitLab user lookup only matches a *public* email for non-admin tokens.
- **Staggered evaluation:** `review --up-to N` limits which criteria are graded;
  the criteria repo's `graider-criteria.yml` `released_up_to` is the default that
  the teacher advances each week.
- **Multiple classes:** if `graider.toml` has `[class.<name>]` sections, pass the
  global `--class <name>` (before the subcommand).
- **AI review credentials:** the review needs credentials for the chosen
  `--backend`. Default is Anthropic (`ANTHROPIC_API_KEY`, or the Claude Code CLI
  on a Pro/Max subscription via `--backend claude-code`). Other providers are
  supported too: `--backend openai` (`OPENAI_API_KEY`), `--backend gemini`
  (`GEMINI_API_KEY`), and `--backend glm` (`GLM_API_KEY`).
- **CI:** the starters' qlty jobs are `allow_failure`; tests must pass. Run
  `graider criteria check` in the criteria repo's CI to catch id/order/cutoff
  mistakes early.

## Topic-specific criteria guidance

When helping a teacher draft criteria (e.g. after `criteria init`), lean on these
research-backed patterns. Each criterion body can carry a `### Levels` block with
`emerging / developing / proficient / exemplary` descriptors; grade the *quality
of reasoning and process*, not just the artifact. See `docs/topic_guides.md` for
sources.

- **Algorithms — use the SOLO taxonomy.** It maps onto the mastery levels:
  emerging ≈ unistructural, developing ≈ multistructural, proficient ≈
  relational, exemplary ≈ extended abstract. Example:

  ```
  ## 3. Algorithm design
  Chooses and justifies an appropriate algorithm/data structure.

  ### Levels
  - emerging: uses a provided algorithm without explanation
  - developing: lists relevant options but can't compare them
  - proficient: selects one and justifies it by complexity and constraints
  - exemplary: assesses trade-offs and adapts the algorithm to edge/failure cases
  ```

- **Testing — assess the process and test quality, not just coverage.** Test-first
  behaviour shows in the git history (tests change with/before the code); reward
  meaningful assertions and negative cases. Example descriptors: emerging = tests
  added at the end / trivial asserts; proficient = tests co-evolve with code, cover
  the documented cases; exemplary = also covers negative/edge cases with clear
  assertions.

- **Design & refactoring — grade the reasoning.** Novices point at code, experts
  reason about quality attributes. Descriptors should climb: names a problem →
  explains why it hurts a quality attribute (coupling/cohesion/readability) →
  justifies the trade-off of the fix. Anchor the discussion on qlty smell counts.

- **Debugging — reward a systematic loop.** A debugging-process criterion:
  reproducible case → hypothesis → fix → regression test. Bug-fix commits are
  natural viva targets.

- **Comprehension — predict/trace viva prompts.** Suggest
  `graider interview --prompt "include predict/trace questions"` — cheap,
  discriminating checks ("what does this return for input X, without running it?").
