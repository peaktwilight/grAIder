# Teachers Manual

Welcome to the grAIder Teachers Manual. This guide walks you through the entire lifecycle of managing a course with grAIder—from course initialization and criteria drafting, to repository setup, bulk grading, AI review, and final report generation.

## 1. Setup and Global Configuration

grAIder requires access to GitLab to create repositories, commit starter templates, and invite students. Configure your credentials once globally using environment variables or a configuration file.

### Environment Variables

Set these variables in your shell profile:

```bash
export GITLAB_URL="https://gitlab.example.edu"  # Defaults to https://gitlab.com
export GITLAB_TOKEN="glpat-YOUR_PERSONAL_ACCESS_TOKEN"  # Requires 'api' scope
```

### Global Configuration File

Alternatively, create a file at `~/.config/graider/config.toml`:

```toml
gitlab_url = "https://gitlab.example.edu"
token = "glpat-YOUR_PERSONAL_ACCESS_TOKEN"
```

### AI Credentials

The AI-powered commands (`criteria init`, `review`, and `interview`) additionally
need access to Claude. Choose one:

*   **Anthropic API key** — set `ANTHROPIC_API_KEY` in your shell. Used by the
    default `--backend api`.
*   **Claude Code CLI** — install the `claude` CLI and run `claude login` to bill
    against a Claude Pro/Max subscription. Selected with `--backend claude-code`.

Beyond Claude, the AI commands can run on other providers via `--backend`:

*   `--backend openai` — OpenAI (or any OpenAI-compatible endpoint). Set
    `OPENAI_API_KEY`, and optionally `OPENAI_BASE_URL`. Pass the provider's
    model id with `--model` (e.g. `--model gpt-4o`).
*   `--backend glm` — GLM (Zhipu). Set `GLM_API_KEY`; `GLM_BASE_URL` defaults to
    the Zhipu endpoint.
*   `--backend gemini` — Google Gemini. Set `GEMINI_API_KEY` (or
    `GOOGLE_API_KEY`) and pass a Gemini `--model`.

Install the optional SDKs as needed: `pip install graider[openai]` or
`pip install graider[google]`.

With `--backend auto` (the default), grAIder uses the Claude Code CLI when it is
installed and no API key is set, otherwise it falls back to the API.

---

## 2. Project Configuration & Multi-Class Support

For each course, initialize a course-specific context directory. grAIder uses a `graider.toml` file in your current working directory to store project defaults.

### Initialize Project

Run the following to scaffold a default `graider.toml`:

```bash
graider init --org "courses/swe-2026" --course "swe-2026" --template python
```

This creates a `graider.toml` in your working directory:

```toml
gitlab_url = "https://gitlab.example.edu"
org = "courses/swe-2026"
template = "python"
course = "swe-2026"
roster = "students.csv"
state = "graider.lock.json"

[criteria]
repo = ""
path = ""
```

### Multi-Class Support

If you manage multiple classes under the same course, you can define class-specific overrides in `graider.toml`:

```toml
gitlab_url = "https://gitlab.com"
template = "python"
course = "swe-2026"

[class.class-a]
org = "courses/swe-2026/class-a"
roster = "roster-class-a.csv"

[class.class-b]
org = "courses/swe-2026/class-b"
roster = "roster-class-b.csv"
```

To run commands for a specific class, pass the `--class` flag:

```bash
graider --class class-a setup
```

---

## 3. Designing and Validating Criteria

grAIder uses Markdown-based files to define milestone criteria for staggered AI evaluation.

### Drafting Criteria

You can draft structured criteria from your course syllabus using Claude:

```bash
graider criteria init --syllabus syllabus.pdf --out ./criteria
```

This drafts a `./criteria/criteria.md` outlining the project brief and criteria list, and initializes `./criteria/graider-criteria.yml` with the default milestone cutoff.

> [!TIP]
> When you refine the drafted criteria (especially the `### Levels` descriptors),
> the grAIder Agent Skill can suggest research-backed patterns for specific topics
> — SOLO-phrased levels for algorithms, test-process and test-quality criteria,
> reasoning-focused design/refactoring descriptors, and debugging-process
> criteria. See the [Topic Guides](topic_guides.md) for the rationale and examples.

### Validating Criteria

To ensure your criteria files are correctly formatted with sequential numeric IDs and valid cutoffs, run:

```bash
graider criteria check ./criteria
```

---

## 4. Provisioning Student Repositories

Once your `graider.toml` and student roster are prepared, you can create repositories on GitLab. The student roster file (e.g., `students.csv`) should map student emails to group numbers:

```csv
email,group
student1@uni.edu,1
student2@uni.edu,1
student3@uni.edu,2
```

### Offline Preview (Dry Run)

Before modifying GitLab, preview the repository structure and group assignments:

```bash
graider setup --dry-run
```

This parses the roster and prints a table of the groups, generated project names, and members.

### Real Execution

To provision the actual repositories:

```bash
graider setup
```

For each group, grAIder:

1.  Creates a private repository in the configured organization path.
2.  Renders the chosen starter template (`python`, `java`, or `cpp`) and commits the files to the repository.
3.  Protects the `main` branch.
4.  Invites the group students to the repository.
5.  Stores the created resources in `graider.lock.json`.

> [!NOTE]
> The `setup` command is idempotent and resumable. If it is interrupted, running it again will resume from the last created project stored in the `graider.lock.json` state file.

---

## 5. Grading the Workspace

To grade student submissions locally (e.g., after checking them out into a local directory structure):

Ensure each repository has a `.graider.yml` configuration (which is automatically generated and committed during `setup`), then run:

```bash
graider grade --workspace /path/to/student/repos --results grade-results.json
```

This runs the code quality checker, unit tests, and coverage metrics over every subdirectory under `/path/to/student/repos` that contains a `.graider.yml`. It saves the unified findings to `grade-results.json`.

---

## 6. Running Staggered AI Reviews

Evaluate codebase design and features against milestones using Claude.

### Run AI Review

```bash
graider review --repo /path/to/student/repo --criteria-dir ./criteria --up-to 2 --results review-results.json
```

*   `--up-to 2`: Limits the AI review to criteria items up to index `2` (either numeric index or criteria ID). If omitted, grAIder checks the `released_up_to` value defined in `./criteria/graider-criteria.yml`.
*   `--backend <auto|api|claude-code>`: Selects how to contact the model.
    *   `api`: Direct API calls.
    *   `claude-code`: Leverages your Claude Pro/Max subscription through the Claude Code CLI for deep code inspection.

### Publishing Feedback (teacher approval gate)

grAIder positions the AI as a **drafting assistant** — you remain the grader of
record. `graider review` only writes an unpublished **draft** (`review-results.json`);
nothing reaches students until you review and approve it with `graider review
publish`.

```bash
# 1. Draft the review (nothing is posted)
graider review --repo /path/to/repo --criteria-dir ./criteria

# 2. Review the drafted feedback, then approve/edit/skip before posting
#    Posts as a comment on an open Merge Request:
graider review publish --feedback mr --project-id "courses/swe-2026/group-1" --branch "main"

#    …or as a new GitLab issue:
graider review publish --feedback issue --project-id "courses/swe-2026/group-1"
```

`graider review publish` prints the rendered feedback and prompts you to
**[a]pprove**, **[e]dit** (opens `$EDITOR`), or **[s]kip**. Pass `--yes` to
bulk-approve once you have built trust in the drafts. The draft is marked
`published` (with a timestamp) after posting, so a re-run won't double-post
unless you pass `--force`. Any prompt-injection warnings are surfaced here for
your attention before anything is published.

### Calibration (anchor submissions)

The teacher hand-grades 2–3 representative submissions with:

```bash
graider calibrate --repo /path/to/student/repo --criteria-dir ./criteria --level 1=proficient --level 2=developing
```

Add `--check` to see how far the AI is from your grades. The anchors are stored in the criteria repo and injected into subsequent reviews so the model matches the instructor's standard. Reports flag projects where the AI verdict and automated metrics disagree.

---

## 7. Generating Reports

Finally, merge functional grades and AI reviews into clean reports for grading.

```bash
graider report --workspace /path/to/student/repos --grade grade-results.json --review review-results.json --out-dir ./reports
```

This merges the data and generates:

1.  **Markdown Reports**: Individual files (e.g., `./reports/group-name.md`) summarizing grade metrics and specific AI review verdicts for each group.
2.  **Summary CSV**: A `./reports/summary.csv` file mapping out all projects, tests passed/failed, coverage percent, and criteria met for a quick upload to your learning management system.

---

## 8. Generating Interview (Viva) Questions

To prepare for an oral exam, grAIder can generate viva questions that probe
whether a student genuinely understands their own project and how it connects to
the course topics. Every question is grounded in the actual repository contents.

```bash
graider interview --repo /path/to/student/repo --criteria-dir ./criteria --out interview.md
```

*   `--topic`: Restrict the questions to one or more topics, by criteria ID or a
    case-insensitive title substring. Repeatable; omit to cover every topic.
*   `--prompt`: Optional free-text guidance to steer the questions (e.g.,
    "focus on concurrency and error handling").
*   `--backend <auto|api|claude-code>`: Same model plumbing as `review` (see
    [AI Credentials](#ai-credentials)).

The generated Markdown lists each question followed by the **key points** a
correct answer should cover and the **red flags** that suggest the student does
not understand their own work. This file is an examiner aid — it contains the
answer key, so keep it to yourself rather than sharing it with students.

```bash
# Only the topics that matter for this exam, with extra steering
graider interview --repo /path/to/repo --criteria-dir ./criteria \
  --topic "Testing" --topic 3 --prompt "probe their design trade-offs"
```

### Process signals

grAIder surfaces git-history signals (commit cadence, contribution split, large code drops) in reports and viva prompts; these are **triage and conversation aids for the teacher, not evidence of misconduct**, and never drive an automatic penalty.

