"""Tests for the Telegram /budget and /recurring commands:

- /budget: user-total budget-vs-actual + one line per set category cap, or a
  no-budget message. Read-only — bot = capture, web = manage.
- /recurring: one line per rule (cadence + next run), or a no-rules message.

Tests run fully offline: no live Telegram connection. Uses the make_update /
make_context helpers and the in-memory db fixture from conftest.py.
"""

from datetime import date

from app.services.budgets import upsert_budget
from app.services.expenses import create_expense_from_data
from bot.handlers.commands import budget_handler, recurring_handler
from tests.conftest import TEST_TG_USER_ID, make_context, make_update


# ---------------------------------------------------------------------------
# /budget — unlinked user
# ---------------------------------------------------------------------------


async def test_budget_unlinked_user_prompted_to_link(db):
    update = make_update(text="/budget", telegram_user_id=99999)
    ctx = make_context(db)
    await budget_handler(update, ctx)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "/link" in reply_text


# ---------------------------------------------------------------------------
# /budget — no budget set
# ---------------------------------------------------------------------------


async def test_budget_no_budget_set(db, linked_user):
    update = make_update(text="/budget", telegram_user_id=TEST_TG_USER_ID)
    ctx = make_context(db)
    await budget_handler(update, ctx)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert reply_text == (
        "No monthly budget set. Set one on the web app to track spending "
        "and get alerts."
    )


# ---------------------------------------------------------------------------
# /budget — total + one set category cap
# ---------------------------------------------------------------------------


async def test_budget_with_total_and_category_cap(db, linked_user, seeded_categories):
    user_id = linked_user.id
    cat = seeded_categories[0]
    today = date.today()

    upsert_budget(db, user_id, "1000.00")
    upsert_budget(db, user_id, "200.00", category_id=cat.id)

    create_expense_from_data(
        db,
        user_id=user_id,
        amount_str="150.00",
        currency="SGD",
        category_id=cat.id,
        expense_date=today,
        merchant="Groceries run",
    )

    update = make_update(text="/budget", telegram_user_id=TEST_TG_USER_ID)
    ctx = make_context(db)
    await budget_handler(update, ctx)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    lines = reply_text.split("\n")

    assert lines[0].startswith("Monthly budget:")
    assert "S$150.00" in lines[0]
    assert "S$1000.00" in lines[0] or "S$1,000.00" in lines[0]
    assert f"· {cat.name}: S$150.00 / S$200.00 (75%)" in reply_text
    assert reply_text.strip().endswith("Manage budgets on the web app.")


# ---------------------------------------------------------------------------
# /recurring — unlinked user
# ---------------------------------------------------------------------------


async def test_recurring_unlinked_user_prompted_to_link(db):
    update = make_update(text="/recurring", telegram_user_id=99999)
    ctx = make_context(db)
    await recurring_handler(update, ctx)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "/link" in reply_text


# ---------------------------------------------------------------------------
# /recurring — no rules
# ---------------------------------------------------------------------------


async def test_recurring_no_rules(db, linked_user):
    update = make_update(text="/recurring", telegram_user_id=TEST_TG_USER_ID)
    ctx = make_context(db)
    await recurring_handler(update, ctx)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert reply_text == "No recurring expenses set up. Add one on the web app."


# ---------------------------------------------------------------------------
# /recurring — with an active rule
# ---------------------------------------------------------------------------


async def test_recurring_with_active_rule(db, linked_user, recurring_rule_factory):
    recurring_rule_factory(merchant="Rent", frequency="monthly", day_of_month=1)

    update = make_update(text="/recurring", telegram_user_id=TEST_TG_USER_ID)
    ctx = make_context(db)
    await recurring_handler(update, ctx)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    lines = reply_text.split("\n")

    assert lines[0] == "Recurring expenses:"
    assert "· Rent —" in reply_text
    assert "/ month, next" in reply_text
    assert "(paused)" not in reply_text
    assert reply_text.strip().endswith("Add or edit recurring on the web app.")


# ---------------------------------------------------------------------------
# /recurring — paused rule gets the "(paused)" suffix
# ---------------------------------------------------------------------------


async def test_recurring_paused_rule_shows_suffix(db, linked_user, recurring_rule_factory):
    recurring_rule_factory(merchant="Netflix", frequency="monthly", day_of_month=1, paused=True)

    update = make_update(text="/recurring", telegram_user_id=TEST_TG_USER_ID)
    ctx = make_context(db)
    await recurring_handler(update, ctx)

    reply_text = update.message.reply_text.call_args[0][0]
    assert "· Netflix —" in reply_text
    assert "(paused)" in reply_text
    assert ", next —" in reply_text


# ---------------------------------------------------------------------------
# /recurring — monthly_nth cadence renders "day {n}"
# ---------------------------------------------------------------------------


async def test_recurring_monthly_nth_cadence(db, linked_user, recurring_rule_factory):
    recurring_rule_factory(
        merchant="Gym", frequency="monthly_nth", day_of_month=15, anchor_date=date(2026, 1, 15)
    )

    update = make_update(text="/recurring", telegram_user_id=TEST_TG_USER_ID)
    ctx = make_context(db)
    await recurring_handler(update, ctx)

    reply_text = update.message.reply_text.call_args[0][0]
    assert "/ day 15, next" in reply_text
