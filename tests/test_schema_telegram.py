"""Telegram schema smoke tests.

Verifies:
- captures.update_id UNIQUE constraint (idempotency foundation)
- make_update() builds an offline Update mock correctly
- User model has Telegram-link columns
"""
import pytest
import sqlalchemy.exc

from tests.conftest import TEST_TG_USER_ID, make_update


def test_capture_unique_update_id(db, capture_factory):
    """Inserting two captures with the same update_id must raise IntegrityError."""
    capture_factory(update_id=5000)

    from app.models.capture import Capture

    duplicate = Capture(
        update_id=5000,
        telegram_user_id=TEST_TG_USER_ID,
        telegram_chat_id=TEST_TG_USER_ID,
        status="queued",
    )
    db.add(duplicate)

    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db.commit()

    db.rollback()


def test_make_update_builds_offline():
    """make_update returns a properly structured offline mock."""
    u = make_update(text="hi", update_id=42)

    assert u.update_id == 42
    assert u.message.text == "hi"
    assert u.effective_user.id == TEST_TG_USER_ID


def test_user_has_telegram_columns(linked_user):
    """User returned by linked_user fixture has telegram_id set."""
    assert linked_user.telegram_id == TEST_TG_USER_ID
