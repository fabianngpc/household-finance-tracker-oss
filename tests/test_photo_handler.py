"""Tests for the photo_handler in bot/handlers/messages.py.

All network calls are mocked — no live Telegram connection, no real file downloads.
Uses in-memory SQLite via db/db_engine/linked_user fixtures from conftest.py.
"""
import pathlib
import pytest
from unittest.mock import AsyncMock, MagicMock

from tests.conftest import make_update, make_context, TEST_TG_USER_ID, TEST_TG_CHAT_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_photo_update(update_id: int = 2001) -> MagicMock:
    """Build an update mock whose message.photo list contains one PhotoSize mock."""
    update = make_update(text="", update_id=update_id)
    photo_size = MagicMock()
    photo_size.file_id = "test_file_id_12345"
    update.message.photo = [photo_size]
    return update


def _make_photo_context(db, downloaded_path: str) -> MagicMock:
    """Context mock: bot.get_file returns a file whose download_to_drive yields downloaded_path."""
    ctx = make_context(db)
    tg_file = MagicMock()
    tg_file.download_to_drive = AsyncMock(return_value=pathlib.Path(downloaded_path))
    ctx.bot.get_file = AsyncMock(return_value=tg_file)
    return ctx


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_unlinked_user_gets_link_prompt_no_capture(db, db_engine, seeded_users):
    """Unlinked user sends a photo → link prompt; no Capture row created."""
    from app.models.capture import Capture
    from bot.handlers.messages import photo_handler

    update = _make_photo_update(update_id=2001)
    ctx = make_context(db)
    ctx.bot.get_file = AsyncMock()  # should never be called

    await photo_handler(update, ctx)

    update.message.reply_text.assert_awaited_once()
    reply_text = update.message.reply_text.call_args.args[0]
    assert "link" in reply_text.lower()

    # No capture created
    assert db.query(Capture).count() == 0
    # get_file was NOT called — no download for unlinked user
    ctx.bot.get_file.assert_not_awaited()


async def test_linked_user_gets_reading_ack(db, db_engine, linked_user, tmp_path):
    """Linked user sends a photo → immediate 'Reading receipt...' reply."""
    from bot.handlers.messages import photo_handler

    fake_image = tmp_path / "receipt_2002.jpg"
    fake_image.touch()

    update = _make_photo_update(update_id=2002)
    ctx = _make_photo_context(db, str(fake_image))

    await photo_handler(update, ctx)

    update.message.reply_text.assert_awaited_once()
    reply_text = update.message.reply_text.call_args.args[0]
    assert "Reading receipt" in reply_text


async def test_linked_user_capture_has_image_path(db, db_engine, linked_user, tmp_path):
    """After photo_handler, a Capture row exists with image_path set to the downloaded temp path."""
    from app.models.capture import Capture
    from bot.handlers.messages import photo_handler

    fake_image = tmp_path / "receipt_2003.jpg"
    fake_image.touch()

    update = _make_photo_update(update_id=2003)
    ctx = _make_photo_context(db, str(fake_image))

    await photo_handler(update, ctx)

    captures = db.query(Capture).all()
    assert len(captures) == 1
    cap = captures[0]
    assert cap.image_path == str(fake_image)


async def test_linked_user_capture_has_empty_raw_text(db, db_engine, linked_user, tmp_path):
    """Photo capture's raw_message is empty string (not None, not any other text)."""
    from app.models.capture import Capture
    from bot.handlers.messages import photo_handler

    fake_image = tmp_path / "receipt_2004.jpg"
    fake_image.touch()

    update = _make_photo_update(update_id=2004)
    ctx = _make_photo_context(db, str(fake_image))

    await photo_handler(update, ctx)

    cap = db.query(Capture).first()
    assert cap is not None
    assert cap.raw_message == ""


async def test_photo_uses_highest_resolution(db, db_engine, linked_user, tmp_path):
    """photo[-1] (highest-res) is used — get_file called with that file_id."""
    from bot.handlers.messages import photo_handler

    fake_image = tmp_path / "receipt_2005.jpg"
    fake_image.touch()

    update = _make_photo_update(update_id=2005)
    # Add a second (higher-res) photo to the list
    high_res = MagicMock()
    high_res.file_id = "high_res_file_id_9999"
    update.message.photo = [update.message.photo[0], high_res]

    ctx = _make_photo_context(db, str(fake_image))

    await photo_handler(update, ctx)

    # get_file should have been called with the LAST (highest-res) file_id
    ctx.bot.get_file.assert_awaited_once_with("high_res_file_id_9999")
