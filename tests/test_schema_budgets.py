"""Budgets, alerts, and recurring schema tests.

Proves every constraint the budgets, alerts, and recurring features
lean on: the UNIQUE constraints and partial unique indexes ARE the dedup
 and idempotency mechanisms, not application logic.
"""
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.budget import Budget, BudgetAlertSent
from app.models.notification import OutboundNotification
from app.models.recurring import RecurringOccurrence
from app.models.expense import Expense


def test_budget_total_unique_per_user(db, seeded_users):
    """Two Budget rows with category_id=None for the same user must collide
    (partial unique index ux_budget_total)."""
    user1, _ = seeded_users
    db.add(Budget(user_id=user1.id, category_id=None, amount_minor=100000))
    db.commit()

    db.add(Budget(user_id=user1.id, category_id=None, amount_minor=200000))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_budget_category_unique_per_user(db, seeded_users, seeded_categories):
    """Two Budget rows with the same (user_id, category_id) must collide
    (partial unique index ux_budget_category); different category_ids are fine."""
    user1, _ = seeded_users
    cat1, cat2 = seeded_categories[0], seeded_categories[1]

    db.add(Budget(user_id=user1.id, category_id=cat1.id, amount_minor=50000))
    db.commit()

    db.add(Budget(user_id=user1.id, category_id=cat1.id, amount_minor=60000))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    # A different category_id for the same user is fine.
    db.add(Budget(user_id=user1.id, category_id=cat2.id, amount_minor=70000))
    db.commit()


def test_budget_alert_unique_per_period_threshold(db, seeded_users):
    """Two BudgetAlertSent rows with the same (user_id, period, threshold)
    must collide (uq_budget_alert); a different period or threshold is fine."""
    user1, _ = seeded_users

    db.add(BudgetAlertSent(user_id=user1.id, period="2026-07", threshold=80))
    db.commit()

    db.add(BudgetAlertSent(user_id=user1.id, period="2026-07", threshold=80))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    # Different period is fine.
    db.add(BudgetAlertSent(user_id=user1.id, period="2026-08", threshold=80))
    db.commit()

    # Different threshold (same period) is fine.
    db.add(BudgetAlertSent(user_id=user1.id, period="2026-07", threshold=100))
    db.commit()


def test_recurring_occurrence_unique_per_period(db, recurring_rule_factory):
    """Two RecurringOccurrence rows with the same (rule_id, period_key) must
    collide (uq_recurring_occurrence); a different period_key is fine."""
    rule = recurring_rule_factory()

    db.add(RecurringOccurrence(rule_id=rule.id, period_key="2026-01-01"))
    db.commit()

    db.add(RecurringOccurrence(rule_id=rule.id, period_key="2026-01-01"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    # Different period_key is fine.
    db.add(RecurringOccurrence(rule_id=rule.id, period_key="2026-02-01"))
    db.commit()


def test_outbound_notification_defaults_pending(db):
    """An OutboundNotification row defaults to status 'pending'."""
    notif = OutboundNotification(telegram_chat_id=123456789, body="Budget alert")
    db.add(notif)
    db.commit()
    db.refresh(notif)

    assert notif.status == "pending"


def test_expense_accepts_recurring_source(db, seeded_users, seeded_categories):
    """An Expense can be created with source='recurring' — no CHECK constraint
    blocks it (Expense.source is a plain String column)."""
    user1, _ = seeded_users
    cat1 = seeded_categories[0]

    exp = Expense(
        user_id=user1.id,
        original_amount_minor=200000,
        original_currency="SGD",
        amount_base_minor=200000,
        fx_rate=1.0,
        fx_rate_date=date(2026, 1, 1),
        category_id=cat1.id,
        occurred_on=date(2026, 1, 1),
        merchant="Rent",
        source="recurring",
    )
    db.add(exp)
    db.commit()
    db.refresh(exp)

    assert exp.source == "recurring"
