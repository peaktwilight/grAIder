"""Thin wrapper around python-gitlab for the operations graider needs."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import gitlab
from gitlab.const import AccessLevel
from gitlab.exceptions import (
    GitlabAuthenticationError,
    GitlabCreateError,
    GitlabError,
    GitlabGetError,
)

from graider.errors import GitLabError
from graider.models import InviteResult, InviteStatus, ProjectRef, RenderedFile


class GitLabClient:
    def __init__(self, url: str, token: str, *, dry_run: bool = False) -> None:
        self._gl = gitlab.Gitlab(url=url, private_token=token, retry_transient_errors=True)
        self.dry_run = dry_run

    def authenticate(self) -> None:
        """Validate the token. Raises GitLabError on failure."""
        try:
            self._gl.auth()
        except GitlabAuthenticationError as exc:
            raise GitLabError(f"GitLab authentication failed: {exc}") from exc

    def get_namespace_id(self, org_path: str) -> int:
        """Resolve a group/org full path (e.g. 'swe/2026') to its numeric id."""
        try:
            group = self._gl.groups.get(org_path)
        except GitlabGetError as exc:
            raise GitLabError(f"GitLab group/org not found: {org_path!r} ({exc})") from exc
        return group.id

    def create_project(
        self, name: str, namespace_id: int, *, visibility: str = "private"
    ) -> ProjectRef | None:
        """Create a project under a namespace. Returns None in dry-run."""
        if self.dry_run:
            return None
        try:
            project = self._gl.projects.create(
                {"name": name, "namespace_id": namespace_id, "visibility": visibility}
            )
        except GitlabCreateError as exc:
            raise GitLabError(f"Could not create project {name!r}: {exc}") from exc
        return ProjectRef(
            id=project.id,
            name=project.name,
            path_with_namespace=project.path_with_namespace,
            web_url=project.web_url,
        )

    def find_user_by_email(self, email: str) -> Any | None:
        """Return the GitLab user matching email, or None.

        Note: for a non-admin token GitLab only matches a user's *public* email,
        so users without a public email fall into `no_account`. Use an admin
        token (or ask students to make their email public) for reliable lookup.
        """
        target = email.strip().lower()
        try:
            matches = self._gl.users.list(search=email, get_all=True)
        except GitlabError as exc:
            raise GitLabError(f"User lookup failed for {email!r}: {exc}") from exc
        for user in matches:
            if target in set(_user_emails(user)):
                return user
        return None

    def invite_member(
        self,
        project_id: int,
        email: str,
        access_level: AccessLevel = AccessLevel.DEVELOPER,
    ) -> InviteResult:
        if self.dry_run:
            return InviteResult(email=email, status=InviteStatus.SKIPPED)

        user = self.find_user_by_email(email)
        if user is None:
            return InviteResult(email=email, status=InviteStatus.NO_ACCOUNT)

        project = self._gl.projects.get(project_id, lazy=True)
        try:
            project.members.create({"user_id": user.id, "access_level": int(access_level)})
        except GitlabCreateError as exc:
            if exc.response_code == 409:  # already a member
                return InviteResult(
                    email=email,
                    status=InviteStatus.ALREADY_MEMBER,
                    username=user.username,
                )
            raise GitLabError(f"Could not add {email} to project {project_id}: {exc}") from exc
        return InviteResult(email=email, status=InviteStatus.INVITED, username=user.username)

    def protect_branch(self, project_id: int, branch: str = "main") -> None:
        """Protect a branch. No-op in dry-run; ignores 'already protected'."""
        if self.dry_run:
            return
        project = self._gl.projects.get(project_id, lazy=True)
        try:
            project.protectedbranches.create({"name": branch})
        except GitlabCreateError as exc:
            if exc.response_code == 409:  # already protected
                return
            raise GitLabError(
                f"Could not protect branch {branch!r} on project {project_id}: {exc}"
            ) from exc

    def commit_files(
        self,
        project_id: int,
        files: list[RenderedFile],
        *,
        message: str = "Initial commit",
        branch: str = "main",
    ) -> None:
        """Create/overwrite files in a single commit. No-op in dry-run.

        For an empty repository this first commit creates `branch`.
        """
        if self.dry_run:
            return
        actions = [{"action": "create", "file_path": f.path, "content": f.content} for f in files]
        project = self._gl.projects.get(project_id, lazy=True)
        try:
            project.commits.create(
                {"branch": branch, "commit_message": message, "actions": actions}
            )
        except GitlabCreateError as exc:
            raise GitLabError(
                f"Could not push initial commit to project {project_id}: {exc}"
            ) from exc


def _user_emails(user: object) -> Iterator[str]:
    """Yield the string email attributes present on a user object.

    Guards with isinstance so it works for both real python-gitlab objects and
    MagicMock test doubles (whose unset attributes are Mocks, not strings).
    """
    for attr in ("email", "public_email"):
        value = getattr(user, attr, None)
        if isinstance(value, str) and value:
            yield value.lower()
