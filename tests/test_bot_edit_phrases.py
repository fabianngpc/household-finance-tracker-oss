"""Tests for natural-language post-save edit phrases:

- PRICE edit phrases ("change the price above", "change price", "change the
  amount", "edit price", "wrong price") re-open the amount confirm step —
  identical behavior to the existing bare "edit" keyword.
- CATEGORY edit phrases ("change the category above", "change category",
  "edit category", "wrong category") show an inline category-picker keyboard.
- setcat callback updates the linked expense's category and confirms.
- Both flows refuse to touch a shared expense (mirrors the /undo guard).
- A normal new capture (no post_save capture on file) is never misread as an
  edit command, even if it happens to contain a trigger word.

Tests run fully offline: real PTB Update objects, class-level patched
Bot.get_me / Message.reply_text / CallbackQuery per this repo's bot test
conventions (see tests/test_bot_shared.py, tests/test_bot_messages.py).
"""

from datetime import date

import pytest

from app.models.capture import Capture
from app.models.category import Category
from app.models.expense import Expense
from app.services.expenses import create_expense_from_data
from app.services.shared_expenses import create_shared_expense
from bot.handlers.messages import setcat_callback, text_handler
from tests.conftest import make_context, make_update
from tests.test_bot_shared import _make_callback_update


# ---------------------------------------------------------------------------
# PRICE edit phrases
# ---------------------------------------------------------------------------


PRICE_PHRASES = [
    "change the price above",
    "change price",
    "change the amount",
    "edit price",
    "wrong price",
]


class TestPriceEditPhrases:
    @pytest.mark.parametrize("phrase", PRICE_PHRASES)
    async def test_phrase_reopens_amount_step(self, db, linked_user, capture_factory, phrase):
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

        update = make_update(text=phrase, update_id=4001)
        ctx = make_context(db)

        await text_handler(update, ctx)

        refreshed = db.query(Capture).filter_by(id=capture_id).first()
        assert refreshed.status == "pending_confirm"
        assert refreshed.confirm_step == "amount"

        update.message.reply_text.assert_called_once()
        assert "amount" in update.message.reply_text.call_args[0][0].lower()

    async def test_price_edit_guard_refuses_shared(
        self, db, linked_user, seeded_users, seeded_categories, mock_frankfurter, capture_factory
    ):
        user1, user2 = seeded_users  # linked_user == user1
        cat1 = seeded_categories[0].id
        cat2 = db.query(Category).filter_by(user_id=user2.id).first().id

        header, payer_row, _ = create_shared_expense(
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

        post_save_cap = capture_factory(
            user_id=user1.id,
            status="done",
            confirm_step="post_save",
            expense_id=payer_row.id,
            amount_str="30.00",
            currency="SGD",
            expense_date="2026-06-21",
        )
        capture_id = post_save_cap.id

        update = make_update(text="change the price above", update_id=4002)
        ctx = make_context(db)

        await text_handler(update, ctx)

        # Capture must NOT flip to pending_confirm — edit was refused
        refreshed = db.query(Capture).filter_by(id=capture_id).first()
        assert refreshed.status == "done"

        update.message.reply_text.assert_called_once()
        reply = update.message.reply_text.call_args[0][0]
        assert "shared expense" in reply.lower()


# ---------------------------------------------------------------------------
# CATEGORY edit phrases
# ---------------------------------------------------------------------------


CATEGORY_PHRASES = [
    "change the category above",
    "change category",
    "edit category",
    "wrong category",
]


class TestCategoryEditPhrases:
    @pytest.mark.parametrize("phrase", CATEGORY_PHRASES)
    async def test_phrase_shows_category_keyboard(
        self, db, linked_user, seeded_categories, capture_factory, phrase
    ):
        user_id = linked_user.id
        other_cat = db.query(Category).filter_by(user_id=user_id, name="Other", is_protected=1).first()

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

        capture_factory(
            user_id=user_id,
            status="done",
            confirm_step="post_save",
            expense_id=expense_id,
            amount_str="15",
            currency="SGD",
            expense_date="2026-06-29",
        )

        update = make_update(text=phrase, update_id=4101)
        ctx = make_context(db)

        await text_handler(update, ctx)

        update.message.reply_text.assert_called_once()
        args, kwargs = update.message.reply_text.call_args
        assert "category" in args[0].lower()

        reply_markup = kwargs.get("reply_markup")
        assert reply_markup is not None
        # Flatten all buttons across rows; every user category should be offered
        all_buttons = [btn for row in reply_markup.inline_keyboard for btn in row]
        assert len(all_buttons) == len(seeded_categories)
        for btn in all_buttons:
            assert btn.callback_data.startswith(f"setcat:{expense_id}:")

    async def test_category_edit_guard_refuses_shared(
        self, db, linked_user, seeded_users, seeded_categories, mock_frankfurter, capture_factory
    ):
        user1, user2 = seeded_users
        cat1 = seeded_categories[0].id
        cat2 = db.query(Category).filter_by(user_id=user2.id).first().id

        header, payer_row, _ = create_shared_expense(
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

        capture_factory(
            user_id=user1.id,
            status="done",
            confirm_step="post_save",
            expense_id=payer_row.id,
            amount_str="30.00",
            currency="SGD",
            expense_date="2026-06-21",
        )

        update = make_update(text="change the category above", update_id=4102)
        ctx = make_context(db)

        await text_handler(update, ctx)

        update.message.reply_text.assert_called_once()
        reply = update.message.reply_text.call_args[0][0]
        assert "shared expense" in reply.lower()


# ---------------------------------------------------------------------------
# setcat callback
# ---------------------------------------------------------------------------


class TestSetCategoryCallback:
    async def test_setcat_updates_category_and_confirms(
        self, db, linked_user, seeded_categories
    ):
        user_id = linked_user.id
        other_cat = db.query(Category).filter_by(user_id=user_id, name="Other", is_protected=1).first()
        target_cat = next(c for c in seeded_categories if c.id != other_cat.id)

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

        update = _make_callback_update(f"setcat:{expense_id}:{target_cat.id}")
        ctx = make_context(db)

        await setcat_callback(update, ctx)

        refreshed = db.query(Expense).filter_by(id=expense_id).first()
        assert refreshed.category_id == target_cat.id

        update.callback_query.answer.assert_awaited_once()
        update.callback_query.message.reply_text.assert_called_once()
        reply = update.callback_query.message.reply_text.call_args[0][0]
        assert target_cat.name in reply
        assert "changed" in reply.lower()


# ---------------------------------------------------------------------------
# Normal capture is not misread as an edit command
# ---------------------------------------------------------------------------


class TestNormalCaptureNotMisread:
    async def test_normal_capture_without_post_save_enqueues(self, db, linked_user):
        user_id = linked_user.id

        update = make_update(text="lunch 40", update_id=4201)
        ctx = make_context(db)

        await text_handler(update, ctx)

        captures = db.query(Capture).filter_by(user_id=user_id).all()
        assert len(captures) == 1
        assert captures[0].status == "queued"
        assert captures[0].raw_message == "lunch 40"

        update.message.reply_text.assert_called_once()
        reply = update.message.reply_text.call_args[0][0].lower()
        assert "processing" in reply or "got it" in reply
