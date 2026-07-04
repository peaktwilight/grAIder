"""Shared domain models."""

from __future__ import annotations

import re

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
