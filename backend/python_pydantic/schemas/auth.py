"""Authentication request schemas."""

from navic_tcp.fastapi_app import (
    AdminLoginIn,
    LoginIn,
    MagicLinkIn,
    VerifyMagicLinkIn,
)

__all__ = ["AdminLoginIn", "LoginIn", "MagicLinkIn", "VerifyMagicLinkIn"]
