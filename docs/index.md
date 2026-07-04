# Welcome to grAIder

grAIder is an AI-powered coursework management and automated evaluation system designed for GitLab. It helps teachers streamline course configuration, repository provisioning, student invitation, testing, code quality checks, and staggered AI reviews. It also allows students to run self-assessment grading and AI feedback locally in their repositories before submission.

## Core Features

*   **Automated GitLab Provisioning**: Automatically generate repositories, push boilerplate code, configure branch protections, and invite students from a roster.
*   **Unified Grading**: Execute code quality checks, run test suites, and measure test coverage under one unified CLI command.
*   **Staggered AI Reviews**: Grade coursework incrementally against milestone criteria using Claude (API or Claude Code CLI), with reviews pushed directly to GitLab Merge Requests or Issues.
*   **Consolidated Reporting**: Merge functional metrics and AI reviews into clean Markdown reports per student group alongside a central grading CSV.
*   **Interview Question Generation**: Produce oral-exam (viva) questions grounded in each student's own project, complete with the key points a correct answer must cover and red flags that betray a shaky understanding.
*   **Student Self-Assessment**: Enable students to run the exact same quality, test, and AI review checks locally before submitting.

## Quick Links

*   [Teachers Manual](teachers.md) — Complete walkthrough from project setup to final grading and reporting.
*   [Students Manual](students.md) — Local grading, self-reviews, and grAIder Agent Skill setup for Claude Code.
*   [Current Implementation Details](current_implementation.md) — Technical details of the implemented features, templates, and integrations.
