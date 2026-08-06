"""Tests for bot/handlers/commands.py — all command handlers.

Tests run fully offline: no live Telegram connection.  Uses the make_update /
make_context helpers and the in-memory db fixture from conftest.py.
"""

from tests.conftest import make_update, make_context, TEST_TG_USER_ID

from bot.handlers.commands import (
    start_handler,
    help_handler,
    balance_handler,
    recent_handler,
    undo_handler,
    link_handler,
)


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------


async def test_start_replies_with_link_mention(db):
    update = make_update(text="/start")
    ctx = make_context(db)
    await start_handler(update, ctx)
    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "/link" in reply_text


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------


async def test_help_lists_recent_and_undo(db):
    update = make_update(text="/help")
    ctx = make_context(db)
    await help_handler(update, ctx)
    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "/recent" in reply_text
    assert "/undo" in reply_text


# ---------------------------------------------------------------------------
# /balance (real implementation — see tests/test_bot_shared.py TestBalanceCommand)
# /budget and /recurring (real implementations — see tests/test_bot_budget_recurring.py)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# /recent — linked user with expenses
# ---------------------------------------------------------------------------


async def test_recent_shows_expenses_for_linked_user(db, linked_user, seeded_categories):
    """linked_user has 2 expenses; reply should contain both merchants."""
    from app.services.expenses import create_expense_from_data
    from datetime import date

    cat = seeded_categories[0]
    create_expense_from_data(
        db,
        user_id=linked_user.id,
        amount_str="10.00",
        currency="SGD",
        category_id=cat.id,
        expense_date=date(2026, 1, 1),
        merchant="Starbucks",
    )
    create_expense_from_data(
        db,
        user_id=linked_user.id,
        amount_str="5.00",
        currency="SGD",
        category_id=cat.id,
        expense_date=date(2026, 1, 2),
        merchant="KFC",
    )

    update = make_update(text="/recent", telegram_user_id=TEST_TG_USER_ID)
    ctx = make_context(db)
    await recent_handler(update, ctx)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "Starbucks" in reply_text
    assert "KFC" in reply_text


# ---------------------------------------------------------------------------
# /recent — linked user with no expenses
# ---------------------------------------------------------------------------


async def test_recent_no_expenses(db, linked_user):
    update = make_update(text="/recent", telegram_user_id=TEST_TG_USER_ID)
    ctx = make_context(db)
    await recent_handler(update, ctx)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    # Should contain "No" or "nothing" (case-insensitive)
    assert "no" in reply_text.lower() or "nothing" in reply_text.lower()


# ---------------------------------------------------------------------------
# /recent — unlinked user prompted to /link
# ---------------------------------------------------------------------------


async def test_recent_unlinked_user_prompted_to_link(db):
    """Telegram user with no linked app account sees a /link prompt."""
    update = make_update(text="/recent", telegram_user_id=99999)  # no linked user
    ctx = make_context(db)
    await recent_handler(update, ctx)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "/link" in reply_text


# ---------------------------------------------------------------------------
# /undo — linked user with expenses
# ---------------------------------------------------------------------------


async def test_undo_deletes_most_recent_expense(db, linked_user, seeded_categories):
    from app.services.expenses import create_expense_from_data, list_expenses
    from datetime import date

    cat = seeded_categories[0]
    # Capture id before the handler closes the shared test session (which would
    # detach linked_user and make lazy-loading fail).
    user_id = linked_user.id
    cat_id = cat.id

    create_expense_from_data(
        db,
        user_id=user_id,
        amount_str="12.00",
        currency="SGD",
        category_id=cat_id,
        expense_date=date(2026, 2, 1),
        merchant="McDonalds",
    )

    update = make_update(text="/undo", telegram_user_id=TEST_TG_USER_ID)
    ctx = make_context(db)
    await undo_handler(update, ctx)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "McDonalds" in reply_text

    # After the handler closes the session it is expired but still reusable.
    remaining = list_expenses(db, user_id=user_id)
    assert len(remaining) == 0


# ---------------------------------------------------------------------------
# /undo — linked user with no expenses
# ---------------------------------------------------------------------------


async def test_undo_nothing_to_undo(db, linked_user):
    update = make_update(text="/undo", telegram_user_id=TEST_TG_USER_ID)
    ctx = make_context(db)
    await undo_handler(update, ctx)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "nothing" in reply_text.lower()


# ---------------------------------------------------------------------------
# /undo — unlinked user
# ---------------------------------------------------------------------------


async def test_undo_unlinked_user_prompted_to_link(db):
    update = make_update(text="/undo", telegram_user_id=88888)
    ctx = make_context(db)
    await undo_handler(update, ctx)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "/link" in reply_text


# ---------------------------------------------------------------------------
# /link — no args
# ---------------------------------------------------------------------------


async def test_link_no_args_shows_usage(db):
    update = make_update(text="/link")
    ctx = make_context(db, args=[])
    await link_handler(update, ctx)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "/link" in reply_text


# ---------------------------------------------------------------------------
# /link — valid code
# ---------------------------------------------------------------------------


async def test_link_valid_code_binds_account(db, seeded_users):
    from app.services.link import generate_link_code
    from app.models.user import User

    user1, _ = seeded_users
    # Capture id before the handler closes the shared test session.
    user1_id = user1.id
    assert user1.telegram_id is None

    code = generate_link_code(db, user1)

    tg_id = 777777777
    update = make_update(text=f"/link {code}", telegram_user_id=tg_id)
    ctx = make_context(db, args=[code])
    await link_handler(update, ctx)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "linked" in reply_text.lower()

    # Re-fetch user after handler closed the session (session is still reusable).
    updated_user = db.query(User).filter(User.id == user1_id).first()
    assert updated_user.telegram_id == tg_id


# ---------------------------------------------------------------------------
# /link — invalid code
# ---------------------------------------------------------------------------


async def test_link_invalid_code_returns_error(db):
    update = make_update(text="/link bad-code-xyz")
    ctx = make_context(db, args=["bad-code-xyz"])
    await link_handler(update, ctx)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    # LinkError("Invalid code.") should contain "Invalid"
    assert "Invalid" in reply_text
