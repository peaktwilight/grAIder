"""Shared domain models."""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, field_validator

# Deliberately loose: this is a sanity check for roster typos, not RFC 5322.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Student(BaseModel):
    email: str
    group_number: str
    name: str | None = None

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not EMAIL_RE.match(value):
            raise ValueError(f"invalid email: {value!r}")
        return value

    @field_validator("group_number")
    @classmethod
    def _non_empty_group(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("missing group number")
        return value

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class Group(BaseModel):
    number: str
    members: list[Student]


class InviteStatus(StrEnum):
    INVITED = "invited"
    ALREADY_MEMBER = "already_member"
    NO_ACCOUNT = "no_account"
    SKIPPED = "skipped"  # dry run only


class InviteResult(BaseModel):
    email: str
    status: InviteStatus
    username: str | None = None


class ProjectRef(BaseModel):
    id: int
    name: str
    path_with_namespace: str
    web_url: str


class RenderedFile(BaseModel):
    path: str  # target path in the repo, e.g. ".graider.yml"
    content: str


class MemberState(BaseModel):
    email: str
    status: InviteStatus
    username: str | None = None


class ProjectState(BaseModel):
    group_number: str
    name: str
    project_id: int
    web_url: str
    path_with_namespace: str
    template: str
    members: list[MemberState] = []


class SetupState(BaseModel):
    gitlab_url: str = ""
    org: str = ""
    # keyed by group_number
    projects: dict[str, ProjectState] = {}


class GradeResult(BaseModel):
    project: str
    template: str
    qlty_issues: int = 0
    qlty_smells: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    coverage_percent: float | None = None
    errors: list[str] = []
