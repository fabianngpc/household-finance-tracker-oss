"""Regression tests for deleting a Telegram-capture-sourced expense.

Bug: `captures.expense_id -> expenses.id` has no ON DELETE behavior, so
SQLite's FK enforcement (foreign_keys=ON in production) raises
IntegrityError on `DELETE FROM expenses WHERE id = ?` when a `captures` row
still references the expense being deleted. This breaks two real user
paths in bot/handlers/messages.py: the "Split 50/50" button
(split_callback) and the post-save "undo" keyword.

Fix under test: delete_expense() must detach any referencing captures rows
(set expense_id = NULL) before deleting the expense, keeping the capture
as a historical/idempotency record.
"""
from datetime import date

from sqlalchemy import text

from app.models.capture import Capture
from app.models.expense import Expense
from app.models.shared_expense import SharedExpense
from app.services.expenses import create_expense_from_data, delete_expense
from bot.handlers.messages import split_callback
from tests.conftest import make_context

_EXPENSE_DATE = date(2026, 6, 20)


class TestDeleteCaptureSourcedExpense:
    def test_delete_detaches_capture_and_succeeds(
        self, db, seeded_users, seeded_categories, capture_factory
    ):
        """delete_expense() on a capture-linked expense must not raise
        IntegrityError, and the referencing capture row must survive with
        expense_id set to NULL (audit log preserved).

        The test's in-memory sqlite connection does not enable FK
        enforcement by default (unlike app.database's production engine),
        so we turn it on explicitly here to faithfully reproduce the
        production `PRAGMA foreign_keys=ON` behavior that triggers the bug.
        """
        db.execute(text("PRAGMA foreign_keys=ON"))
        user1, _ = seeded_users
        cat1 = seeded_categories[0].id

        expense = create_expense_from_data(
            db,
            user_id=user1.id,
            amount_str="12.00",
            currency="SGD",
            category_id=cat1,
            expense_date=_EXPENSE_DATE,
            merchant="Kopitiam",
            source="telegram",
        )
        expense_id = expense.id

        capture = capture_factory(
            user_id=user1.id,
            status="done",
            expense_id=expense_id,
            amount_str="12.00",
        )
        capture_id = capture.id

        # Must not raise sqlalchemy.exc.IntegrityError
        delete_expense(db, user_id=user1.id, expense_id=expense_id)

        assert db.query(Expense).filter_by(id=expense_id).count() == 0

        db.expire_all()
        surviving_capture = db.query(Capture).filter_by(id=capture_id).first()
        assert surviving_capture is not None, "Capture row must survive the delete"
        assert surviving_capture.expense_id is None
        assert surviving_capture.status == "done"

    async def test_split_callback_on_captured_expense_succeeds(
        self, db, linked_user, seeded_users, seeded_categories, mock_frankfurter,
        capture_factory,
    ):
        """The "Split 50/50" button deletes the original (capture-sourced)
        solo expense after creating the shared pair. This must succeed even
        though a captures row still points at the original expense id."""
        db.execute(text("PRAGMA foreign_keys=ON"))
        user1, user2 = seeded_users  # linked_user == user1
        cat1 = seeded_categories[0].id

        expense = create_expense_from_data(
            db,
            user_id=user1.id,
            amount_str="20.00",
            currency="SGD",
            category_id=cat1,
            expense_date=_EXPENSE_DATE,
            merchant="Dinner",
            source="telegram",
        )
        expense_id = expense.id

        capture = capture_factory(
            user_id=user1.id,
            status="done",
            expense_id=expense_id,
            amount_str="20.00",
        )
        capture_id = capture.id

        from tests.test_bot_shared import _make_callback_update

        update = _make_callback_update(f"split:{expense_id}")
        ctx = make_context(db)

        await split_callback(update, ctx)

        # Original solo expense is gone, no crash.
        assert db.query(Expense).filter_by(id=expense_id).count() == 0

        # Shared header + 2 children created correctly.
        headers = db.query(SharedExpense).all()
        assert len(headers) == 1
        children = db.query(Expense).filter_by(shared_expense_id=headers[0].id).all()
        assert len(children) == 2

        # The capture row survives, detached from the deleted expense.
        # split_callback's `finally: db.close()` expires/detaches
        # previously-loaded objects, so re-query by the id captured above
        # rather than touching the (now stale) `capture` instance.
        surviving_capture = db.query(Capture).filter_by(id=capture_id).first()
        assert surviving_capture is not None
        assert surviving_capture.expense_id is None

        update.callback_query.message.reply_text.assert_called_once()
        reply_text = update.callback_query.message.reply_text.call_args[0][0]
        assert "Your half:" in reply_text
