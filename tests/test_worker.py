"""Tests for bot/worker.py — process_one and run_worker.

All tests run fully offline: bot is an AsyncMock, no live Telegram connection.
Uses in-memory SQLite via db_engine + db fixtures from conftest.py.
"""
import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.extractor import StubExtractor
from app.models.capture import Capture
from app.models.expense import Expense
from app.models.job import Job
from tests.fakes import FakeExtractor, make_result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _process(bot, extractor, db_engine, db):
    """Call process_one with in-memory fixtures (helper to reduce repetition)."""
    from bot.worker import process_one
    return await process_one(bot, extractor, db_engine, lambda: db)


# ---------------------------------------------------------------------------
# Task 1: process_one — claim, extract, process, reply
# ---------------------------------------------------------------------------

async def test_high_confidence_auto_saves(db, db_engine, linked_user, capture_factory, job_factory):
    """'12 lunch' -> expense saved, job done, summary message containing the amount sent."""
    capture = capture_factory(raw_message="12 lunch", user_id=linked_user.id)
    job_factory(capture_id=capture.id)

    # Store values before process_one may close / expire the session
    capture_id = capture.id
    chat_id = capture.telegram_chat_id
    user_id = linked_user.id

    bot = AsyncMock()
    result = await _process(bot, StubExtractor(), db_engine, db)

    assert result is True

    # Expense was created with source='telegram'
    expenses = db.query(Expense).filter_by(user_id=user_id).all()
    assert len(expenses) == 1
    assert expenses[0].source == "telegram"

    # Capture status is 'done'
    fresh_capture = db.get(Capture, capture_id)
    assert fresh_capture.status == "done"

    # Summary message sent to the correct chat with the amount
    bot.send_message.assert_awaited_once()
    call_kwargs = bot.send_message.call_args.kwargs
    assert call_kwargs["chat_id"] == chat_id
    assert "12" in call_kwargs["text"]

    # Job is marked done
    job = db.query(Job).filter_by(capture_id=capture_id).first()
    assert job.status == "done"


async def test_low_confidence_enters_confirm_flow(db, db_engine, linked_user, capture_factory, job_factory):
    """'lunch' (no number) -> no expense, capture parks in pending_confirm, asks for amount."""
    capture = capture_factory(raw_message="lunch", user_id=linked_user.id)
    job_factory(capture_id=capture.id)

    capture_id = capture.id
    chat_id = capture.telegram_chat_id
    user_id = linked_user.id

    bot = AsyncMock()
    result = await _process(bot, StubExtractor(), db_engine, db)

    assert result is True

    # No expense created
    expenses = db.query(Expense).filter_by(user_id=user_id).all()
    assert len(expenses) == 0

    # Capture parked in pending_confirm with confirm_step='amount'
    fresh_capture = db.get(Capture, capture_id)
    assert fresh_capture.status == "pending_confirm"
    assert fresh_capture.confirm_step == "amount"

    # Bot asked for the amount
    bot.send_message.assert_awaited_once()
    call_kwargs = bot.send_message.call_args.kwargs
    assert call_kwargs["chat_id"] == chat_id
    assert "amount" in call_kwargs["text"].lower()

    # Job is marked done
    job = db.query(Job).filter_by(capture_id=capture_id).first()
    assert job.status == "done"


async def test_no_job_returns_false(db, db_engine, linked_user):
    """No pending jobs -> returns False, no message sent."""
    bot = AsyncMock()
    result = await _process(bot, StubExtractor(), db_engine, db)

    assert result is False
    bot.send_message.assert_not_awaited()


async def test_empty_queue_returns_false(db, db_engine, linked_user):
    """Alias for no-job case: empty queue returns False (for -k 'empty' selector)."""
    bot = AsyncMock()
    result = await _process(bot, StubExtractor(), db_engine, db)
    assert result is False


async def test_duplicate_guard_done_capture(db, db_engine, linked_user, capture_factory, job_factory):
    """Capture already status='done' with a stray pending job -> no new expense; job done."""
    capture = capture_factory(raw_message="12 lunch", user_id=linked_user.id)
    job_factory(capture_id=capture.id)

    capture_id = capture.id
    user_id = linked_user.id

    # First run: processes normally, creates expense
    bot1 = AsyncMock()
    await _process(bot1, StubExtractor(), db_engine, db)

    expense_count_before = db.query(Expense).filter_by(user_id=user_id).count()
    assert expense_count_before == 1

    # Stray pending job for the same already-done capture
    stray_job = job_factory(capture_id=capture_id, status="pending")
    stray_job_id = stray_job.id

    # Second run: should be a no-op (duplicate guard)
    bot2 = AsyncMock()
    result = await _process(bot2, StubExtractor(), db_engine, db)

    assert result is True

    # No new expense
    expense_count_after = db.query(Expense).filter_by(user_id=user_id).count()
    assert expense_count_after == expense_count_before

    # Stray job marked done
    stray = db.get(Job, stray_job_id)
    assert stray.status == "done"


# ---------------------------------------------------------------------------
# Task 2: run_worker() entrypoint and poll loop
# ---------------------------------------------------------------------------

async def test_run_worker_processes_then_stops(monkeypatch):
    """run_worker calls process_one; sleeps when queue empty; exits cleanly on cancel."""
    import bot.worker

    calls = []

    async def fake_process_one(bot_arg, extractor, engine, db_factory):
        calls.append("process_one")
        return False  # no job -> loop should sleep

    async def fake_drain(bot_arg, db_factory, engine):
        calls.append("drain")
        return 0

    sleep_calls = []

    async def fake_sleep(t):
        sleep_calls.append(t)
        raise asyncio.CancelledError()  # terminate after first sleep

    mock_bot = AsyncMock()

    monkeypatch.setattr(bot.worker, "process_one", fake_process_one)
    monkeypatch.setattr(bot.worker, "drain_outbound_notifications", fake_drain)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(bot.worker, "Bot", lambda token: mock_bot)
    monkeypatch.setattr(bot.worker, "BOT_TOKEN", "FAKE:TOKEN")
    monkeypatch.setattr(bot.worker, "engine", MagicMock())
    monkeypatch.setattr(bot.worker, "SessionLocal", MagicMock())

    with pytest.raises(asyncio.CancelledError):
        await bot.worker.run_worker(poll_interval=0.5)

    assert len(calls) >= 1, "process_one should have been called at least once"
    assert len(sleep_calls) == 1, "sleep should be called when no job available"
    assert sleep_calls[0] == 0.5, "sleep should use the poll_interval"


# ---------------------------------------------------------------------------
# Photo capture paths + temp cleanup + config-driven extractor
# ---------------------------------------------------------------------------


async def test_photo_unreadable_sends_couldnt_read_prompt(
    db, db_engine, linked_user, capture_factory, job_factory, tmp_path
):
    """Photo capture + unreadable result → 'Couldn't read it' message, not plain amount prompt."""
    fake_image = tmp_path / "receipt_unreadable.jpg"
    fake_image.touch()

    capture = capture_factory(
        raw_message="",
        user_id=linked_user.id,
        image_path=str(fake_image),
    )
    job_factory(capture_id=capture.id)

    capture_id = capture.id
    chat_id = capture.telegram_chat_id

    bot = AsyncMock()
    extractor = FakeExtractor(make_result(amount_str=None, confidence_amount=0.0))
    result = await _process(bot, extractor, db_engine, db)

    assert result is True

    fresh_capture = db.get(Capture, capture_id)
    assert fresh_capture.status == "pending_confirm"
    assert fresh_capture.confirm_step == "amount"

    bot.send_message.assert_awaited_once()
    call_kwargs = bot.send_message.call_args.kwargs
    assert call_kwargs["chat_id"] == chat_id
    assert "Couldn't read it" in call_kwargs["text"]
    assert "amount" in call_kwargs["text"].lower()


async def test_photo_temp_file_deleted_after_success(
    db, db_engine, linked_user, capture_factory, job_factory, tmp_path
):
    """After a successful process_one for a photo capture, the temp image file is deleted."""
    fake_image = tmp_path / "receipt_success_cleanup.jpg"
    fake_image.touch()
    assert fake_image.exists()

    capture = capture_factory(
        raw_message="",
        user_id=linked_user.id,
        image_path=str(fake_image),
    )
    job_factory(capture_id=capture.id)

    bot = AsyncMock()
    # High-confidence result so process_one succeeds and saves
    extractor = FakeExtractor(make_result(amount_str="12.50", confidence_amount=0.9))
    await _process(bot, extractor, db_engine, db)

    assert not fake_image.exists(), "temp image should be deleted after process_one"


async def test_photo_temp_file_deleted_after_failure(
    db, db_engine, linked_user, capture_factory, job_factory, tmp_path
):
    """Even when the extractor raises, the temp image file is still cleaned up."""
    fake_image = tmp_path / "receipt_fail_cleanup.jpg"
    fake_image.touch()
    assert fake_image.exists()

    capture = capture_factory(
        raw_message="",
        user_id=linked_user.id,
        image_path=str(fake_image),
    )
    job_factory(capture_id=capture.id)

    class _BrokenExtractor:
        async def extract(self, text, image_path=None):
            raise RuntimeError("Ollama is down")

    bot = AsyncMock()
    await _process(bot, _BrokenExtractor(), db_engine, db)

    assert not fake_image.exists(), "temp image should be deleted even on extractor failure"


async def test_failure_notifies_user_and_marks_failed(
    db, db_engine, linked_user, capture_factory, job_factory
):
    """Regression: when processing raises, the user must be told — not left
    on the 'Got it, processing...' ack forever. The capture is marked failed
    and a 'Couldn't process' message is sent to their chat."""
    capture = capture_factory(raw_message="lunch 90000 IDR", user_id=linked_user.id)
    job_factory(capture_id=capture.id)
    capture_id = capture.id
    chat_id = capture.telegram_chat_id

    class _BrokenExtractor:
        async def extract(self, text, image_path=None):
            raise RuntimeError("FX lookup failed")

    bot = AsyncMock()
    await _process(bot, _BrokenExtractor(), db_engine, db)

    fresh_capture = db.get(Capture, capture_id)
    assert fresh_capture.status == "failed"

    bot.send_message.assert_awaited_once()
    call_kwargs = bot.send_message.call_args.kwargs
    assert call_kwargs["chat_id"] == chat_id
    assert "Couldn't process" in call_kwargs["text"]


async def test_text_capture_low_confidence_plain_prompt(
    db, db_engine, linked_user, capture_factory, job_factory
):
    """Text capture (no image_path) with low confidence → plain 'What's the amount?' prompt."""
    capture = capture_factory(raw_message="lunch", user_id=linked_user.id)
    job_factory(capture_id=capture.id)

    chat_id = capture.telegram_chat_id

    bot = AsyncMock()
    extractor = FakeExtractor(make_result(amount_str=None, confidence_amount=0.0))
    await _process(bot, extractor, db_engine, db)

    bot.send_message.assert_awaited_once()
    call_kwargs = bot.send_message.call_args.kwargs
    assert call_kwargs["chat_id"] == chat_id
    assert "What's the amount?" in call_kwargs["text"]
    assert "Couldn't read it" not in call_kwargs["text"]
