# Feature Requests

This page tracks the forward-looking roadmap. The features previously listed
here — context-aware configuration, multi-class support, and feedback via merge
requests or issues — have all shipped and are documented in the
[Teachers Manual](teachers.md) and [Current Implementation](current_implementation.md).

Active proposals are tracked as issues in the project's GitLab issue tracker.
The highlights:

## Multi-Provider LLM Support

Today the AI features (`criteria init`, `review`, `interview`) run on Claude,
either through the Anthropic API or the Claude Code CLI. We want to let a course
choose its provider — **OpenAI**, **Google Gemini**, and **GLM (Zhipu)** — via
configuration, so schools can use whichever model they have credentials or
budget for. GLM and other OpenAI-compatible endpoints would be reached through a
single configurable base URL.

As a prerequisite, the criteria-drafting code will be routed through the shared
`ModelBackend` abstraction that `review` and `interview` already use, so every
AI feature picks up new providers uniformly.

## Cost and Token Reporting

Surface token usage and an estimated cost per run so teachers grading a whole
class can see what a review sweep costs before and after running it.

## Review Caching

Re-running `review` currently re-sends the whole repository every time. A
content-hash cache would skip unchanged repositories, cutting cost and wall time
for large classes.

## More Starter Languages

Starter templates cover Python, Java, and C++. JavaScript/TypeScript, Rust, and
Go are common in coursework and are natural next additions.
