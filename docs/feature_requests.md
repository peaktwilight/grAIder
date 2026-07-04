# Feature Requests

The following features are planned to be implemented after the current implementation plan is completed:

## Setup and Config

*   **Context-Aware Configuration**: Configuration will be stored directly within a coursework project directory. This means running the `graider` tool from inside a folder like `/home/sandro/IdeaProjects/docs-st` will automatically fetch the relevant repositories and documentation based on the current project context.
*   **Multiple Class Support**: When teaching multiple classes simultaneously, a CLI flag will be available to explicitly select which class to operate on. If no flag is provided, the tool will default to using the first available class.

## Feedback Mechanisms

*   **Feedback via Merge Requests**: Students will create a merge request containing their changes. The AI review and feedback will be provided directly as comments on that specific merge request.
*   **Feedback through Issues**: For workflows where students commit directly to the `main` branch, the tool will generate feedback in the form of an issue that the students can subsequently check and address.
