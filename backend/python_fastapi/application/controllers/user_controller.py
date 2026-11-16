"""User controller: profile, preferences and student services.

These handlers exercise the backend models, sessions and Pydantic schemas
directly.  Bus-pass issuance/verification stay delegated
because they depend on transactional rules shared with the TCP application.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone

from fastapi import Depends, HTTPException

from backend.python_fastapi.application.controllers.base import Controller
from backend.python_fastapi.application.core.dependencies import current_user
from backend.python_pydantic.schemas.user import (
    FeedbackIn,
    PreferencesIn,
    SupportIn,
    UserProfileIn,
)
from backend.python_sqlalchemy.database.session import SessionLocal
from backend.python_sqlalchemy.models import (
    Feedback,
    SupportTicket,
    User,
    UserPreferences,
)
from navic_tcp.fastapi_app import _audit, _iso


def user_profile(user=Depends(current_user)):
    return {
        key: user.get(key)
        for key in (
            "email",
            "user_id",
            "first_name",
            "last_name",
            "account_type",
            "full_name",
            "avatar_url",
            "phone",
            "department",
            "usn",
            "role",
            "active",
            "is_profile_complete",
        )
    }


def update_user_profile(data: UserProfileIn, user=Depends(current_user)):
    if not user.get("id"):
        raise HTTPException(404, "User profile not found")
    with SessionLocal() as db:
        account = db.get(User, user["id"])
        if account is None or not account.active:
            raise HTTPException(404, "User profile not found")
        account.full_name = data.full_name
        account.phone = data.phone
        account.department = data.department
        account.usn = data.usn or None
        account.is_profile_complete = True
        db.commit()
        db.refresh(account)
        return {
            "id": account.id,
            "username": account.username,
            "user_id": account.user_id,
            "email": account.email,
            "first_name": account.first_name,
            "last_name": account.last_name,
            "account_type": account.account_type,
            "full_name": account.full_name,
            "avatar_url": account.avatar_url,
            "phone": account.phone,
            "department": account.department,
            "usn": account.usn,
            "role": account.role,
            "active": account.active,
            "is_profile_complete": account.is_profile_complete,
        }


def get_user_preferences(user=Depends(current_user)):
    with SessionLocal() as db:
        row = db.get(UserPreferences, user["id"])
        return row.values if row else PreferencesIn().model_dump()


def save_user_preferences(data: PreferencesIn, user=Depends(current_user)):
    with SessionLocal() as db:
        row = db.get(UserPreferences, user["id"])
        if row is None:
            row = UserPreferences(user_id=user["id"], values=data.model_dump())
            db.add(row)
        else:
            row.values = data.model_dump()
            row.updated_at = datetime.now(timezone.utc)
        db.commit()
        return row.values


def create_feedback(data: FeedbackIn, user=Depends(current_user)):
    with SessionLocal() as db:
        row = Feedback(user_id=user["id"], rating=data.rating, category=data.category, comments=data.comments)
        db.add(row)
        db.commit()
        db.refresh(row)
        return {"id": row.id, "status": row.status, "created_at": _iso(row.created_at)}


def create_support_ticket(data: SupportIn, user=Depends(current_user)):
    with SessionLocal() as db:
        row = SupportTicket(
            ticket_number=f"NAV-{datetime.now(timezone.utc):%Y%m%d}-{secrets.token_hex(4).upper()}",
            user_id=user["id"],
            subject=data.subject,
            category=data.category,
            description=data.description,
            contact=data.contact,
            priority=data.priority,
            status="OPEN",
        )
        db.add(row)
        _audit(db, user, "create", "support_ticket", row.ticket_number, f"category={data.category};priority={data.priority}")
        db.commit()
        return {"ticket_id": row.ticket_number, "status": row.status, "created_at": _iso(row.created_at)}


def support_info():
    return {"email": os.getenv("CBTMS_SUPPORT_EMAIL", "").strip() or None, "phone": os.getenv("CBTMS_SUPPORT_PHONE", "").strip() or None}


def user_terms():
    return {
        "title": "CBTMS usage and privacy terms",
        "approval_required": True,
        "sections": [
            {"title": "Usage policy", "body": "Use CBTMS only for legitimate college transport and support purposes. Final institutional policy text requires approval."},
            {"title": "Privacy and GPS data", "body": "Vehicle location is collected from installed tracking devices."},
            {"title": "User responsibilities", "body": "Provide accurate information, protect account access and use emergency reporting only for genuine concerns."},
            {"title": "Acceptable use and reporting", "body": "Do not misuse, disrupt or attempt to access data outside your authorization. Use Support to report issues."},
        ],
    }


class UserController(Controller):
    operations = {
        "/api/user/me": user_profile,
        "/api/user/profile": update_user_profile,
        "/api/users/me/preferences": {
            "GET": get_user_preferences,
            "PUT": save_user_preferences,
        },
        "/api/feedback": create_feedback,
        "/api/support": create_support_ticket,
        "/api/support/info": support_info,
        "/api/user/terms": user_terms,
    }


__all__ = [
    "UserController",
    "create_feedback",
    "create_support_ticket",
    "get_user_preferences",
    "save_user_preferences",
    "support_info",
    "update_user_profile",
    "user_profile",
    "user_terms",
]
