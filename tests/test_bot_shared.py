"""Tests for the Telegram surface of shared expenses:

- /balance: real per-currency directional reply (bot/handlers/commands.py)
- split_callback: atomic "Split 50/50 with {partner}" button tap
  (bot/handlers/messages.py) — must never lose the original expense if the
  create-shared-expense step fails
- /undo and the undo keyword: refuse to delete shared children

Tests run fully offline: no live Telegram connection. Uses make_update /
make_context helpers and the in-memory db fixture from conftest.py.
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock

from app.models.expense import Expense
from app.models.shared_expense import SharedExpense
from app.services.expenses import create_expense_from_data
from app.services.shared_expenses import create_shared_expense
from bot.handlers.commands import balance_handler, undo_handler
from bot.handlers.messages import split_callback
from tests.conftest import TEST_TG_USER_ID, make_context, make_update


def _make_callback_update(data: str, telegram_user_id: int = TEST_TG_USER_ID):
    """Build a minimal callback-query update (no live Telegram connection).

    Mirrors make_update's shape but for a callback_query tap instead of a
    text message: `.effective_user`, `.callback_query.data`,
    `.callback_query.answer` (AsyncMock), `.callback_query.message.reply_text`
    (AsyncMock).
    """
    from telegram import Chat, User as TGUser

    tg_user = TGUser(id=telegram_user_id, first_name="Test", is_bot=False)
    chat = Chat(id=telegram_user_id, type="private")

    message = MagicMock()
    message.reply_text = AsyncMock()

    callback_query = MagicMock()
    callback_query.data = data
    callback_query.answer = AsyncMock()
    callback_query.message = message

    update = MagicMock()
    update.effective_user = tg_user
    update.effective_chat = chat
    update.callback_query = callback_query

    return update


# ---------------------------------------------------------------------------
# /balance
# ---------------------------------------------------------------------------


class TestBalanceCommand:
    async def test_all_settled_up(self, db, linked_user, seeded_users):
        update = make_update(text="/balance")
        ctx = make_context(db)
        await balance_handler(update, ctx)

        update.message.reply_text.assert_called_once()
        reply_text = update.message.reply_text.call_args[0][0]
        assert reply_text == "All settled up."

    async def test_directional_line(
        self, db, linked_user, seeded_users, seeded_categories, mock_frankfurter
    ):
        user1, user2 = seeded_users  # linked_user == user1 (Alice)
        cat1 = seeded_categories[0].id
        cat2 = db.query(type(seeded_categories[0])).filter_by(user_id=user2.id).first().id

        # user1 (linked, Alice) pays a shared SGD expense -> user2 (partner) owes user1
        create_shared_expense(
            db,
            user1.id,
            user2.id,
            "100.00",
            "SGD",
            date(2026, 6, 15),
            "equal",
            cat1,
            cat2,
            {},
        )

        update = make_update(text="/balance")
        ctx = make_context(db)
        await balance_handler(update, ctx)

        update.message.reply_text.assert_called_once()
        reply_text = update.message.reply_text.call_args[0][0]
        assert "owes you SGD" in reply_text
        assert user2.display_name in reply_text

    async def test_multi_currency_alphabetical(
        self, db, linked_user, seeded_users, seeded_categories, mock_frankfurter
    ):
        user1, user2 = seeded_users
        cat1 = seeded_categories[0].id
        cat2 = db.query(type(seeded_categories[0])).filter_by(user_id=user2.id).first().id
        occurred_on = date(2026, 6, 15)

        create_shared_expense(
            db, user2.id, user1.id, "50.00", "USD", occurred_on, "equal", cat2, cat1, {}
        )
        create_shared_expense(
            db, user2.id, user1.id, "40.00", "EUR", occurred_on, "equal", cat2, cat1, {}
        )

        update = make_update(text="/balance")
        ctx = make_context(db)
        await balance_handler(update, ctx)

        reply_text = update.message.reply_text.call_args[0][0]
        lines = reply_text.split("\n")
        eur_idx = next(i for i, l in enumerate(lines) if "EUR" in l)
        usd_idx = next(i for i, l in enumerate(lines) if "USD" in l)
        assert eur_idx < usd_idx


# ---------------------------------------------------------------------------
# Split callback
# ---------------------------------------------------------------------------


class TestSplitCallback:
    async def test_split_creates_shared_and_confirms(
        self, db, linked_user, seeded_users, seeded_categories, mock_frankfurter
    ):
        user1, user2 = seeded_users  # linked_user == user1
        cat1 = seeded_categories[0].id

        expense = create_expense_from_data(
            db,
            user_id=user1.id,
            amount_str="20.00",
            currency="SGD",
            category_id=cat1,
            expense_date=date(2026, 6, 20),
            merchant="Dinner",
            source="telegram",
        )
        expense_id = expense.id

        update = _make_callback_update(f"split:{expense_id}")
        ctx = make_context(db)

        await split_callback(update, ctx)

        # Original solo expense is gone
        assert db.query(Expense).filter_by(id=expense_id).count() == 0

        # A SharedExpense header exists with exactly 2 children
        headers = db.query(SharedExpense).all()
        assert len(headers) == 1
        children = db.query(Expense).filter_by(shared_expense_id=headers[0].id).all()
        assert len(children) == 2

        update.callback_query.answer.assert_awaited_once()
        update.callback_query.message.reply_text.assert_called_once()
        reply_text = update.callback_query.message.reply_text.call_args[0][0]
        assert "Your half:" in reply_text
        assert user2.display_name in reply_text

    async def test_split_failure_preserves_original(
        self, db, linked_user, seeded_users, seeded_categories, mocker
    ):
        user1, _ = seeded_users
        cat1 = seeded_categories[0].id

        expense = create_expense_from_data(
            db,
            user_id=user1.id,
            amount_str="20.00",
            currency="SGD",
            category_id=cat1,
            expense_date=date(2026, 6, 20),
            merchant="Dinner",
            source="telegram",
        )
        expense_id = expense.id

        mocker.patch(
            "bot.handlers.messages.create_shared_expense",
            side_effect=RuntimeError("frankfurter down"),
        )

        update = _make_callback_update(f"split:{expense_id}")
        ctx = make_context(db)

        await split_callback(update, ctx)

        # Original solo expense STILL exists — never deleted
        assert db.query(Expense).filter_by(id=expense_id).count() == 1
        # No SharedExpense row was created
        assert db.query(SharedExpense).count() == 0

        update.callback_query.message.reply_text.assert_called_once()
        reply_text = update.callback_query.message.reply_text.call_args[0][0]
        assert "unchanged" in reply_text.lower()


# ---------------------------------------------------------------------------
# /undo guard against shared children
# ---------------------------------------------------------------------------


class TestUndoGuard:
    async def test_undo_refuses_shared(
        self, db, linked_user, seeded_users, seeded_categories, mock_frankfurter
    ):
        user1, user2 = seeded_users  # linked_user == user1
        cat1 = seeded_categories[0].id
        cat2 = db.query(type(seeded_categories[0])).filter_by(user_id=user2.id).first().id

        # linked_user (user1) is the payer -> their share row is the most recent expense
        create_shared_expense(
            db,
            user1.id,
            user2.id,
            "30.00",
            "SGD",
            date(2026, 6, 21),
            "equal",
            cat1,
            cat2,
            {},
        )

        before_count = db.query(Expense).count()

        update = make_update(text="/undo")
        ctx = make_context(db)
        await undo_handler(update, ctx)

        update.message.reply_text.assert_called_once()
        reply_text = update.message.reply_text.call_args[0][0]
        assert "shared expense" in reply_text.lower()

        # Nothing was deleted
        assert db.query(Expense).count() == before_count
