"""Shared domain models."""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, computed_field, field_validator, model_validator

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


class PerformanceLevel(StrEnum):
    """Ordered analytic-rubric mastery levels (emerging is lowest)."""

    EMERGING = "emerging"
    DEVELOPING = "developing"
    PROFICIENT = "proficient"
    EXEMPLARY = "exemplary"


# The scale in teaching order, and the levels that count as "met" (proficient+).
LEVEL_ORDER: tuple[PerformanceLevel, ...] = (
    PerformanceLevel.EMERGING,
    PerformanceLevel.DEVELOPING,
    PerformanceLevel.PROFICIENT,
    PerformanceLevel.EXEMPLARY,
)
MET_LEVELS: frozenset[PerformanceLevel] = frozenset(
    {PerformanceLevel.PROFICIENT, PerformanceLevel.EXEMPLARY}
)


class CriteriaItem(BaseModel):
    id: str  # stable, e.g. "3" or "testing"
    title: str
    body: str = ""
    order: int  # 1-based position
    levels: dict[str, str] = {}  # optional per-level descriptors, keyed by level name


class Criteria(BaseModel):
    brief: str = ""
    items: list[CriteriaItem] = []


class CriterionVerdict(BaseModel):
    id: str
    title: str
    level: PerformanceLevel
    evidence: list[str]  # e.g. "src/calc.py:12 — no error handling"
    comment: str
    next_step: str = ""  # feed-forward: one concrete next step for criteria below proficient

    @model_validator(mode="before")
    @classmethod
    def _backfill_level(cls, data: object) -> object:
        # Back-compat: results/tests that pass a boolean `met` and no `level`
        # map True -> proficient, False -> emerging.
        if isinstance(data, dict) and "level" not in data and "met" in data:
            met = data["met"]  # type: ignore
            return {
                **data,
                "level": PerformanceLevel.PROFICIENT if met else PerformanceLevel.EMERGING,
            }
        return data

    @computed_field  # serialized, so review-results.json still carries `met`
    @property
    def met(self) -> bool:
        return self.level in MET_LEVELS


class Usage(BaseModel):
    """Token counts for one AI run."""

    input_tokens: int = 0
    output_tokens: int = 0


class ReviewOutput(BaseModel):
    """Exactly what the model returns (structured-output schema)."""

    overall_summary: str
    criteria: list[CriterionVerdict]


class ReviewResult(BaseModel):
    """Persisted result = model output + run metadata."""

    project: str
    head_sha: str
    model: str
    cutoff: str
    overall_summary: str
    criteria: list[CriterionVerdict]
    warnings: list[str] = []  # teacher-facing flags, e.g. possible prompt injection
    published: bool = False  # posted to GitLab via `review publish` (teacher-approved)
    published_at: str = ""  # ISO timestamp of publication


class LevelDescriptors(BaseModel):
    """Per-level rubric descriptors drafted for one criterion."""

    emerging: str = ""
    developing: str = ""
    proficient: str = ""
    exemplary: str = ""


class DraftItem(BaseModel):
    title: str
    body: str  # description + suggested evaluation questions for graders
    levels: LevelDescriptors | None = None


class CriteriaDraft(BaseModel):
    brief: str
    items: list[DraftItem]


class InterviewQuestion(BaseModel):
    question: str
    key_points: list[str]  # what a correct answer must cover
    red_flags: list[str]  # signs the student doesn't understand their own project


class InterviewTopic(BaseModel):
    topic: str
    questions: list[InterviewQuestion]


class InterviewOutput(BaseModel):
    topics: list[InterviewTopic]
