"""Telegram account linking service.

Provides:
  - generate_link_code  — creates a single-use 15-min code stored on the User row
  - bind_telegram_id    — validates code and binds a Telegram ID (called from /link bot command)
  - resolve_user_by_telegram_id — reverse lookup used by the capture write-path
"""

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.user import User

LINK_CODE_TTL_MINUTES = 15


class LinkError(Exception):
    """Raised with a user-facing message for the /link bot command to relay."""


def _now_naive_utc() -> datetime:
    """Current time as naive UTC (matches the naive-UTC convention used throughout the codebase)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def generate_link_code(db: Session, user: User) -> str:
    """Generate (or regenerate) a single-use link code for *user*.

    Sets ``user.link_code`` and ``user.link_code_expires_at`` (naive UTC, ~15 min).
    Commits and returns the new code string.
    """
    code = secrets.token_urlsafe(16)
    user.link_code = code
    user.link_code_expires_at = _now_naive_utc() + timedelta(minutes=LINK_CODE_TTL_MINUTES)
    db.commit()
    return code


def bind_telegram_id(db: Session, code: str, telegram_id: int) -> User:
    """Bind *telegram_id* to the user identified by *code*.

    Raises:
        LinkError: if the code is unknown, expired, or already bound to a different Telegram ID.
    Returns:
        The updated User on success (link_code and link_code_expires_at cleared).
    """
    user = db.query(User).filter(User.link_code == code).first()
    if user is None:
        raise LinkError("Invalid code.")

    now = _now_naive_utc()
    if user.link_code_expires_at is None or user.link_code_expires_at < now:
        raise LinkError("Code expired. Generate a new one in the web app.")

    if user.telegram_id is not None and user.telegram_id != telegram_id:
        raise LinkError("This code belongs to a different account.")

    user.telegram_id = telegram_id
    user.link_code = None
    user.link_code_expires_at = None
    db.commit()
    return user


def resolve_user_by_telegram_id(db: Session, telegram_id: int) -> User | None:
    """Return the User bound to *telegram_id*, or None if not linked."""
    return db.query(User).filter(User.telegram_id == telegram_id).first()
