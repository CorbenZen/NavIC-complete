"""Schemas for the primary User ID + password authentication flow.

These replace the email-based registration contract for normal student and
teacher accounts.  Email remains an optional attribute on the ORM model for the
administrator, Google and legacy magic-link accounts, but it is never part of
this request/response contract.
"""

from __future__ import annotations

import os
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# 3-32 characters, starts with a letter or digit, then letters, digits, dot,
# underscore or hyphen.  IDs are normalised to upper case before comparison and
# storage, so "navic001" and "NAVIC001" are the same account.
_USER_ID = re.compile(r"^[A-Z0-9][A-Z0-9._-]{2,31}$")
_DEFAULT_USN = r"^[A-Za-z0-9][A-Za-z0-9/-]{2,31}$"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_user_id(value: str) -> str:
    """Canonical form used for uniqueness checks and storage."""
    return value.strip().upper()


def validate_user_id_format(value: str) -> str:
    """Return the normalised ID or raise ``ValueError`` with a clear message."""
    normalised = normalize_user_id(value)
    if not normalised:
        raise ValueError("Please enter your User ID.")
    if not _USER_ID.fullmatch(normalised):
        raise ValueError(
            "User ID must be 3-32 characters, start with a letter or digit, "
            "and contain only letters, digits, dots, underscores or hyphens."
        )
    return normalised


def validate_login_identifier(value: str) -> str:
    """Accept a normal User ID or the configured administrator's email address.

    The administrator continues to authenticate with ``ADMIN_EMAIL`` and
    ``ADMIN_PASSWORD_HASH``; the sign-in form therefore accepts that email in
    the same field as a User ID.  Email identifiers are lower-cased so the
    comparison with the configured address is case-insensitive.
    """
    if not isinstance(value, str):
        raise ValueError("Please enter your ID and password.")
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("Please enter your ID and password.")
    if "@" in trimmed:
        lowered = trimmed.lower()
        if len(lowered) <= 254 and _EMAIL.fullmatch(lowered):
            return lowered
        raise ValueError("Enter a valid User ID or administrator email address.")
    return validate_user_id_format(trimmed)


class IdLoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=512)

    @field_validator("user_id", mode="before")
    @classmethod
    def clean_user_id(cls, value):
        if not isinstance(value, str):
            raise ValueError("Please enter your ID and password.")
        return validate_login_identifier(value)

    @model_validator(mode="before")
    @classmethod
    def require_both_fields(cls, value):
        if isinstance(value, dict):
            user_id = value.get("user_id")
            password = value.get("password")
            if (
                not isinstance(user_id, str)
                or not user_id.strip()
                or not isinstance(password, str)
                or not password
            ):
                raise ValueError("Please enter your ID and password.")
        return value


class RegisterAccountIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    account_type: Literal["student", "teacher"]
    user_id: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)
    usn_id: str | None = Field(default=None, max_length=64)

    @field_validator("first_name", "last_name", mode="before")
    @classmethod
    def clean_name(cls, value):
        if not isinstance(value, str):
            raise ValueError("Enter a valid name.")
        value = " ".join(value.split())
        if not value or any(ord(character) < 32 for character in value):
            raise ValueError("Enter a valid name.")
        return value

    @field_validator("account_type", mode="before")
    @classmethod
    def clean_account_type(cls, value):
        if not isinstance(value, str) or value.strip().lower() not in {"student", "teacher"}:
            raise ValueError("Choose Student or Teacher.")
        return value.strip().lower()

    @field_validator("user_id", mode="before")
    @classmethod
    def clean_user_id(cls, value):
        if not isinstance(value, str):
            raise ValueError("Please enter your User ID.")
        return validate_user_id_format(value)

    @field_validator("usn_id", mode="before")
    @classmethod
    def clean_usn(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Enter a valid student USN.")
        value = value.strip().upper()
        if not value:
            return None
        pattern = os.getenv("USN_REGEX", _DEFAULT_USN)
        try:
            valid = re.fullmatch(pattern, value, flags=re.IGNORECASE) is not None
        except re.error:
            raise ValueError("Student USN validation is misconfigured.") from None
        if not valid:
            raise ValueError("Enter a valid student USN.")
        return value

    @field_validator("password")
    @classmethod
    def clean_password(cls, value):
        if not value or not value.strip():
            raise ValueError("Please enter a password.")
        if not any(character.isalpha() for character in value):
            raise ValueError("Password must contain at least one letter.")
        return value

    @model_validator(mode="after")
    def validate_registration(self):
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        if self.account_type == "student" and not self.usn_id:
            raise ValueError("USN ID is required for student accounts.")
        if self.account_type == "teacher" and self.usn_id:
            raise ValueError("Teacher accounts do not use a USN ID.")
        if self.password.strip().upper() == self.user_id:
            raise ValueError("Password must not be the same as your User ID.")
        return self


__all__ = [
    "IdLoginIn",
    "RegisterAccountIn",
    "normalize_user_id",
    "validate_login_identifier",
    "validate_user_id_format",
]
