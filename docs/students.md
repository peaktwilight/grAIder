# Students Manual

Welcome to grAIder! This manual shows you how to use grAIder to perform local grading and self-reviews of your coursework before submitting it to GitLab.

## 1. Local Repository Configuration

When your repository is provisioned by your instructor, it will contain a `.graider.yml` configuration file at its root. This file tells grAIder how your project is structured and where to find the course grading criteria.

A typical `.graider.yml` looks like this:

```yaml
course: swe-2026
template: python
criteria:
  repo: course/criteria
  path: grading/rubric.yml
```

---

## 2. Local Grading & Self-Assessment

You can run quality tools, tests, and coverage checks locally to verify that your repository meets all automated grading rules before pushing.

Run this command from the root of your repository:

```bash
graider grade
```

*By default, this looks for `.graider.yml` in the current directory (`--repo .`).*

This command will:

1.  Run the code quality checker (`qlty`).
2.  Run the language-specific test suite.
3.  Calculate your code coverage.
4.  Generate a local `grade-results.json` file summarizing the results.

---

## 3. Running Local AI Self-Reviews

To check your implementation against the course criteria using AI, you can run a local review.

> [!NOTE]
> The AI review needs access to Claude. Either set `ANTHROPIC_API_KEY` in your
> shell, or install the `claude` CLI and run `claude login` to use a Claude
> Pro/Max subscription (`--backend claude-code`).

If you have a local copy of the grading criteria folder (or your instructor has provided access to the criteria repository), run:

```bash
graider review --criteria-dir /path/to/criteria
```

Alternatively, if your `.graider.yml` specifies a `criteria.repo` that you have read access to, you can run:

```bash
graider review
```

This will:

1.  Read the criteria from the specified source.
2.  Retrieve only the currently released criteria based on the course milestone cutoff.
3.  Perform an AI evaluation of your codebase using Claude and output a detailed verdict for each criterion.
4.  Save the review report to `review-results.json`.

> [!TIP]
> You can preview which criteria are currently in-scope for evaluation without running the actual AI model by using the `--dry-run` flag:
> ```bash
> graider review --dry-run
> ```

---

## 4. Using grAIder with Claude Code

If you use **Claude Code** for development, you can install the grAIder Agent Skill. This allows Claude Code to directly run `graider grade` and `graider review` on your behalf, helping you fix lint errors or failing tests interactively.

### Install the Agent Skill

To install the skill globally for Claude Code:

```bash
graider skills install
```

*This places the skill files in `~/.claude/skills`.*

To install the skill locally for the current project only:

```bash
graider skills install --project
```

*This places the skill files in `./.claude/skills`.*

Once installed, you can ask Claude Code questions like:

*   *"Run grAIder and help me fix any failing tests."*
*   *"Am I meeting the current milestone criteria? Run a grAIder review."*
