"""Tests for bot/handlers/messages.py — text_handler routing.

Task 1: new-capture idempotent enqueue + ack + unlinked user prompt
Task 2: confirm-flow reply routing + restart-safe resume + post-save keywords
"""

import pytest
from app.models.capture import Capture
from app.models.job import Job
from tests.conftest import make_update, make_context, TEST_TG_USER_ID, TEST_TG_OTHER_ID


# ---------------------------------------------------------------------------
# Task 1: New capture — idempotent enqueue + ack
# ---------------------------------------------------------------------------


async def test_new_capture_enqueued_and_acked(db, linked_user):
    """Linked user sending a new message creates one capture + one job and is acked."""
    from bot.handlers.messages import text_handler

    user_id = linked_user.id  # capture before handler closes the session

    update = make_update(text="12 lunch", update_id=2001)
    ctx = make_context(db)

    await text_handler(update, ctx)

    # Re-open a fresh query on the same in-memory engine via a new db call
    captures = db.query(Capture).filter_by(user_id=user_id).all()
    jobs = db.query(Job).all()
    assert len(captures) == 1
    assert captures[0].status == "queued"
    assert len(jobs) == 1
    assert jobs[0].status == "pending"

    update.message.reply_text.assert_called_once()
    reply = update.message.reply_text.call_args[0][0].lower()
    assert "processing" in reply or "got it" in reply


async def test_idempotent_duplicate_update_id(db, linked_user):
    """Duplicate update_id delivery does not create a second capture or job."""
    from bot.handlers.messages import text_handler

    user_id = linked_user.id  # capture before handler closes the session

    update = make_update(text="12 lunch", update_id=2002)
    ctx = make_context(db)

    await text_handler(update, ctx)
    await text_handler(update, ctx)

    captures = db.query(Capture).filter_by(user_id=user_id).all()
    jobs = db.query(Job).all()
    assert len(captures) == 1
    assert len(jobs) == 1


async def test_unlinked_user_gets_link_prompt(db, seeded_users):
    """Unlinked user receives a /link prompt; no capture or job is created."""
    from bot.handlers.messages import text_handler

    # seeded_users: users exist but have no telegram_id (unlinked)
    update = make_update(text="12 lunch", update_id=2003, telegram_user_id=TEST_TG_OTHER_ID)
    ctx = make_context(db)

    await text_handler(update, ctx)

    assert db.query(Capture).count() == 0
    assert db.query(Job).count() == 0

    update.message.reply_text.assert_called_once()
    assert "/link" in update.message.reply_text.call_args[0][0]


# ---------------------------------------------------------------------------
# Task 2: Confirm-flow reply routing + restart-safe resume + post-save keywords
# ---------------------------------------------------------------------------


async def test_confirm_valid_amount_saves_expense(db, linked_user, capture_factory):
    """
    Pre-existing pending_confirm capture (restart simulation via capture_factory).
    Replying with a valid amount triggers apply_confirm_input, saves expense,
    and the reply contains the saved amount. No new capture is enqueued.
    """
    from app.models.expense import Expense
    from bot.handlers.messages import text_handler

    user_id = linked_user.id

    # Simulate state that was written before a restart (DB-only, no in-process handler)
    pending = capture_factory(
        user_id=user_id,
        status="pending_confirm",
        confirm_step="amount",
        currency="SGD",
        merchant="lunch",
        expense_date="2026-06-29",
    )
    capture_id = pending.id

    update = make_update(text="12", update_id=3001)
    ctx = make_context(db)

    await text_handler(update, ctx)

    # Verify capture advanced to done
    saved = db.query(Capture).filter_by(id=capture_id).first()
    assert saved is not None
    assert saved.status == "done"

    # Verify expense was created
    assert db.query(Expense).filter_by(user_id=user_id).count() == 1

    # No new capture should have been enqueued (still only one capture total)
    assert db.query(Capture).count() == 1

    # Reply should mention the amount
    update.message.reply_text.assert_called_once()
    reply = update.message.reply_text.call_args[0][0]
    assert "12" in reply


async def test_confirm_invalid_amount_stays_pending(db, linked_user, capture_factory):
    """
    Replying with invalid text to a pending_confirm capture leaves it pending
    and the bot re-asks for the amount.
    """
    from bot.handlers.messages import text_handler

    user_id = linked_user.id

    pending = capture_factory(
        user_id=user_id,
        status="pending_confirm",
        confirm_step="amount",
        currency="SGD",
        merchant="lunch",
        expense_date="2026-06-29",
    )
    capture_id = pending.id

    update = make_update(text="abc", update_id=3002)
    ctx = make_context(db)

    await text_handler(update, ctx)

    # Capture must still be pending_confirm
    refreshed = db.query(Capture).filter_by(id=capture_id).first()
    assert refreshed.status == "pending_confirm"

    # Reply should prompt for the amount
    update.message.reply_text.assert_called_once()
    assert "amount" in update.message.reply_text.call_args[0][0].lower()


async def test_confirm_resumes_from_db_row_only(db, linked_user, capture_factory):
    """
    Restart-safety proof: capture row created via capture_factory (not via any
    prior handler invocation). text_handler finds it purely from the DB and
    advances the confirm flow — no in-memory handler state needed.
    """
    from app.models.expense import Expense
    from bot.handlers.messages import text_handler

    user_id = linked_user.id

    # Only the DB row exists — simulates a fresh process restart
    pending = capture_factory(
        user_id=user_id,
        status="pending_confirm",
        confirm_step="amount",
        currency="SGD",
        merchant="coffee",
        expense_date="2026-06-29",
    )
    capture_id = pending.id

    update = make_update(text="5.50", update_id=3003)
    ctx = make_context(db)

    await text_handler(update, ctx)

    saved = db.query(Capture).filter_by(id=capture_id).first()
    assert saved.status == "done"
    assert db.query(Expense).filter_by(user_id=user_id).count() == 1


async def test_post_save_undo_deletes_expense(db, linked_user, capture_factory):
    """
    With a post_save capture and a linked expense, replying 'undo' removes
    the expense and confirms deletion.
    """
    from datetime import date
    from app.models.category import Category
    from app.models.expense import Expense
    from app.services.expenses import create_expense_from_data
    from bot.handlers.messages import text_handler

    user_id = linked_user.id

    # Resolve the seeded "Other" category for this user
    other_cat = db.query(Category).filter_by(user_id=user_id, name="Other", is_protected=1).first()
    assert other_cat is not None, "Seed data missing: no 'Other' category for user"

    # Create the expense via the canonical write-path
    expense = create_expense_from_data(
        db,
        user_id=user_id,
        amount_str="15",
        currency="SGD",
        category_id=other_cat.id,
        expense_date=date(2026, 6, 29),
        merchant="lunch",
        source="telegram",
    )
    expense_id = expense.id

    # Create a post_save capture pointing at the expense
    post_save_cap = capture_factory(
        user_id=user_id,
        status="done",
        confirm_step="post_save",
        expense_id=expense_id,
        amount_str="15",
        currency="SGD",
        expense_date="2026-06-29",
    )

    update = make_update(text="undo", update_id=3004)
    ctx = make_context(db)

    await text_handler(update, ctx)

    # Expense must be deleted
    assert db.query(Expense).filter_by(id=expense_id).count() == 0

    # Reply confirms removal
    update.message.reply_text.assert_called_once()
    assert "removed" in update.message.reply_text.call_args[0][0].lower()


async def test_post_save_edit_re_enters_confirm(db, linked_user, capture_factory):
    """
    With a post_save capture, replying 'edit' sets the capture back to
    pending_confirm/amount and asks for the amount.
    """
    from bot.handlers.messages import text_handler

    user_id = linked_user.id

    post_save_cap = capture_factory(
        user_id=user_id,
        status="done",
        confirm_step="post_save",
        amount_str="15",
        currency="SGD",
        expense_date="2026-06-29",
    )
    capture_id = post_save_cap.id

    update = make_update(text="edit", update_id=3005)
    ctx = make_context(db)

    await text_handler(update, ctx)

    refreshed = db.query(Capture).filter_by(id=capture_id).first()
    assert refreshed.status == "pending_confirm"
    assert refreshed.confirm_step == "amount"

    update.message.reply_text.assert_called_once()
    assert "amount" in update.message.reply_text.call_args[0][0].lower()
