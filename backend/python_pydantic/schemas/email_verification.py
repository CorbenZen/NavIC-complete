"""Schemas for password login and email verification operations."""

import os
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from navic_tcp.auth import normalize_email, valid_email


class PasswordLoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=512)

    @field_validator("email", mode="before")
    @classmethod
    def validate_email(cls, value):
        if not isinstance(value, str):
            raise ValueError("Enter a valid email address.")
        value = normalize_email(value)
        if not valid_email(value):
            raise ValueError("Enter a valid email address.")
        return value


class VerifyEmailIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=512)


class ResendVerificationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)

    @field_validator("email", mode="before")
    @classmethod
    def validate_email(cls, value):
        if not isinstance(value, str):
            raise ValueError("Enter a valid email address.")
        value = normalize_email(value)
        if not valid_email(value):
            raise ValueError("Enter a valid email address.")
        return value


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=10, max_length=128)
    confirm_password: str = Field(min_length=10, max_length=128)
    account_type: str
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

    @field_validator("email", mode="before")
    @classmethod
    def validate_gmail(cls, value):
        if not isinstance(value, str):
            raise ValueError("Enter a valid Gmail address.")
        value = normalize_email(value)
        if not valid_email(value) or not value.endswith("@gmail.com"):
            raise ValueError("Enter a valid Gmail address ending in @gmail.com.")
        return value

    @field_validator("account_type", mode="before")
    @classmethod
    def validate_account_type(cls, value):
        if not isinstance(value, str) or value.strip().lower() not in {"student", "teacher"}:
            raise ValueError("Choose Student or Teacher.")
        return value.strip().lower()

    @field_validator("usn_id", mode="before")
    @classmethod
    def validate_usn(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Enter a valid student USN.")
        value = value.strip().upper()
        if not value:
            return None
        pattern = os.getenv("USN_REGEX", r"^[A-Za-z0-9][A-Za-z0-9/-]{2,31}$")
        try:
            valid = re.fullmatch(pattern, value, flags=re.IGNORECASE) is not None
        except re.error:
            raise ValueError("Student USN validation is misconfigured.") from None
        if not valid:
            raise ValueError("Enter a valid student USN.")
        return value

    @model_validator(mode="after")
    def validate_registration(self):
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        if self.account_type == "student" and not self.usn_id:
            raise ValueError("USN ID is required for student accounts.")
        if self.account_type == "teacher" and self.usn_id:
            raise ValueError("Teacher accounts do not use a USN ID.")
        return self


__all__ = ["PasswordLoginIn", "RegisterIn", "ResendVerificationIn", "VerifyEmailIn"]
