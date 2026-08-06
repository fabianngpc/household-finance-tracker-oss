"""
Unit tests for the recurring-expenses service (date math +
idempotent catch-up).

Behaviors covered:
- due_dates clamps 31st-anchored monthly rules across a full year (no
  ValueError) and clamps a Feb-29 (leap-year) anchor in non-leap years.
- due_dates for weekly rules yields anchor + timedelta(weeks=k); Nth-of-month
  uses day_of_month.
- end_date truncates the due list; a paused rule generates nothing;
  generate_from as the start excludes earlier periods.
- generate_due creates exactly the right number of Expense rows (each dated
  to its real due date, source="recurring") plus one RecurringOccurrence
  marker per period, for a rule anchored months in the past.
- Running generate_due a SECOND time is a no-op: zero new expenses, zero new
  markers (idempotency via UNIQUE(rule_id, period_key)).
- A shared rule fans out into a SharedExpense header + two linked Expense
  rows per period; compute_balance reflects the split; the marker's
  shared_expense_id is set.
- Each generation enqueues an OutboundNotification matching the solo/shared/
  backfill copy from the UI spec.
- pause_rule/resume_rule: resuming advances generate_from to "today" so the
  paused window is never backfilled.
- update_rule mutates future generation only — it never touches previously
  generated Expense rows.
"""

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.expense import Expense
from app.models.notification import OutboundNotification
from app.models.recurring import RecurringOccurrence, RecurringRule
from app.services.balance import compute_balance
from app.services.recurring import (
    create_rule,
    delete_rule,
    due_dates,
    generate_due,
    list_rules,
    pause_rule,
    resume_rule,
    update_rule,
)


# ---------------------------------------------------------------------------
# due_dates: date math + clamping
# ---------------------------------------------------------------------------


def test_due_dates_monthly_31_clamps_across_full_year(recurring_rule_factory):
    rule = recurring_rule_factory(
        frequency="monthly",
        day_of_month=31,
        anchor_date=date(2026, 1, 31),
        generate_from=date(2026, 1, 31),
    )
    dates = due_dates(rule, start=rule.generate_from, until=date(2026, 12, 31))

    assert len(dates) == 12
    # Jan 31 -> Feb 28 (2026 not a leap year) -> Mar 31 -> Apr 30 ...
    assert dates[0] == date(2026, 1, 31)
    assert dates[1] == date(2026, 2, 28)
    assert dates[2] == date(2026, 3, 31)
    assert dates[3] == date(2026, 4, 30)
    assert dates[-1] == date(2026, 12, 31)


def test_due_dates_feb29_anchor_clamps_in_non_leap_years(recurring_rule_factory):
    # 2024 is a leap year (anchor exists); step forward into 2025 (non-leap).
    rule = recurring_rule_factory(
        frequency="monthly",
        day_of_month=29,
        anchor_date=date(2024, 2, 29),
        generate_from=date(2024, 2, 29),
    )
    dates = due_dates(rule, start=rule.generate_from, until=date(2025, 3, 1))

    assert date(2024, 2, 29) in dates
    # Feb 2025 is not a leap year -> clamps to Feb 28, no ValueError raised.
    assert date(2025, 2, 28) in dates
    assert all(d.month != 2 or d.day <= 28 or d.year % 4 == 0 for d in dates)


def test_due_dates_weekly_uses_timedelta_weeks(recurring_rule_factory):
    rule = recurring_rule_factory(
        frequency="weekly",
        anchor_date=date(2026, 1, 5),
        generate_from=date(2026, 1, 5),
        day_of_month=None,
    )
    dates = due_dates(rule, start=rule.generate_from, until=date(2026, 1, 26))

    assert dates == [
        date(2026, 1, 5),
        date(2026, 1, 12),
        date(2026, 1, 19),
        date(2026, 1, 26),
    ]


def test_due_dates_monthly_nth_uses_day_of_month(recurring_rule_factory):
    rule = recurring_rule_factory(
        frequency="monthly_nth",
        day_of_month=15,
        anchor_date=date(2026, 1, 15),
        generate_from=date(2026, 1, 15),
    )
    dates = due_dates(rule, start=rule.generate_from, until=date(2026, 4, 15))

    assert dates == [
        date(2026, 1, 15),
        date(2026, 2, 15),
        date(2026, 3, 15),
        date(2026, 4, 15),
    ]


def test_due_dates_generate_from_excludes_earlier_periods(recurring_rule_factory):
    rule = recurring_rule_factory(
        frequency="monthly",
        day_of_month=1,
        anchor_date=date(2026, 1, 1),
        generate_from=date(2026, 3, 1),  # paused-window skip: start later than anchor
    )
    dates = due_dates(rule, start=rule.generate_from, until=date(2026, 5, 1))

    assert date(2026, 1, 1) not in dates
    assert date(2026, 2, 1) not in dates
    assert dates == [date(2026, 3, 1), date(2026, 4, 1), date(2026, 5, 1)]


def test_due_dates_end_date_truncates(recurring_rule_factory):
    rule = recurring_rule_factory(
        frequency="monthly",
        day_of_month=1,
        anchor_date=date(2026, 1, 1),
        generate_from=date(2026, 1, 1),
        end_date=date(2026, 3, 15),
    )
    dates = due_dates(rule, start=rule.generate_from, until=date(2026, 6, 1))
    assert dates == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]


# ---------------------------------------------------------------------------
# generate_due: idempotent catch-up (solo)
# ---------------------------------------------------------------------------


def test_generate_due_paused_rule_generates_nothing(db, recurring_rule_factory):
    rule = recurring_rule_factory(paused=True)
    occurrences = generate_due(db, rule, today=date(2026, 6, 1))
    assert occurrences == []
    assert db.query(Expense).count() == 0
    assert db.query(RecurringOccurrence).count() == 0


def test_generate_due_backfills_correct_count_and_real_due_dates(
    db, recurring_rule_factory
):
    # Anchored 3 months back relative to "today".
    rule = recurring_rule_factory(
        frequency="monthly",
        day_of_month=1,
        anchor_date=date(2026, 4, 1),
        generate_from=date(2026, 4, 1),
    )
    today = date(2026, 7, 1)

    occurrences = generate_due(db, rule, today=today)

    assert len(occurrences) == 4  # Apr, May, Jun, Jul
    expenses = db.query(Expense).filter(Expense.source == "recurring").all()
    assert len(expenses) == 4
    occurred_dates = sorted(e.occurred_on for e in expenses)
    assert occurred_dates == [
        date(2026, 4, 1),
        date(2026, 5, 1),
        date(2026, 6, 1),
        date(2026, 7, 1),
    ]
    for exp in expenses:
        assert exp.source == "recurring"

    markers = db.query(RecurringOccurrence).all()
    assert len(markers) == 4
    for m in markers:
        assert m.rule_id == rule.id
        assert m.expense_id is not None


def test_generate_due_second_run_is_a_noop(db, recurring_rule_factory):
    rule = recurring_rule_factory(
        frequency="monthly",
        day_of_month=1,
        anchor_date=date(2026, 4, 1),
        generate_from=date(2026, 4, 1),
    )
    today = date(2026, 7, 1)

    generate_due(db, rule, today=today)
    first_expense_count = db.query(Expense).count()
    first_marker_count = db.query(RecurringOccurrence).count()

    second_occurrences = generate_due(db, rule, today=today)

    assert second_occurrences == []
    assert db.query(Expense).count() == first_expense_count
    assert db.query(RecurringOccurrence).count() == first_marker_count


# ---------------------------------------------------------------------------
# generate_due: shared fan-out
# ---------------------------------------------------------------------------


def test_generate_due_shared_rule_fans_out_and_updates_balance(
    db, recurring_rule_factory, seeded_users, seeded_categories
):
    user1, user2 = seeded_users
    rule = recurring_rule_factory(
        frequency="monthly",
        day_of_month=1,
        anchor_date=date(2026, 6, 1),
        generate_from=date(2026, 6, 1),
        is_shared=True,
        split_method="equal",
        partner_category_id=seeded_categories[0].id,
        amount_minor=10000,  # S$100.00
    )
    today = date(2026, 6, 1)

    occurrences = generate_due(db, rule, today=today)

    assert len(occurrences) == 1
    marker = occurrences[0]
    assert marker.shared_expense_id is not None
    assert marker.expense_id is None

    children = (
        db.query(Expense)
        .filter(Expense.shared_expense_id == marker.shared_expense_id)
        .all()
    )
    assert len(children) == 2
    assert {c.user_id for c in children} == {user1.id, user2.id}

    balances = compute_balance(db, user1.id, user2.id)
    assert balances.get("SGD") == 5000  # partner owes payer half of S$100


# ---------------------------------------------------------------------------
# generate_due: outbound notifications
# ---------------------------------------------------------------------------


def test_generate_due_single_period_enqueues_solo_notification(
    db, recurring_rule_factory, seeded_users
):
    user1, _ = seeded_users
    user1.telegram_id = 555
    db.commit()

    rule = recurring_rule_factory(
        merchant="Netflix",
        amount_minor=1599,
        frequency="monthly",
        day_of_month=1,
        anchor_date=date(2026, 6, 1),
        generate_from=date(2026, 6, 1),
    )

    generate_due(db, rule, today=date(2026, 6, 1))

    notifications = db.query(OutboundNotification).all()
    assert len(notifications) == 1
    assert notifications[0].telegram_chat_id == 555
    assert "Netflix" in notifications[0].body
    assert "15.99" in notifications[0].body


def test_generate_due_backfill_batch_enqueues_single_caught_up_notification(
    db, recurring_rule_factory, seeded_users
):
    user1, _ = seeded_users
    user1.telegram_id = 555
    db.commit()

    rule = recurring_rule_factory(
        merchant="Rent",
        frequency="monthly",
        day_of_month=1,
        anchor_date=date(2026, 1, 1),
        generate_from=date(2026, 1, 1),
    )

    generate_due(db, rule, today=date(2026, 4, 1))

    notifications = db.query(OutboundNotification).all()
    assert len(notifications) == 1
    assert "caught up" in notifications[0].body.lower()
    assert "Rent" in notifications[0].body


# ---------------------------------------------------------------------------
# Rule CRUD / pause / resume / edit-future-only
# ---------------------------------------------------------------------------


def test_create_rule_sets_generate_from_to_anchor(db, seeded_users, seeded_categories):
    user1, _ = seeded_users
    rule = create_rule(
        db,
        owner_user_id=user1.id,
        amount_minor=5000,
        currency="SGD",
        category_id=seeded_categories[0].id,
        merchant="Gym",
        frequency="monthly",
        day_of_month=10,
        anchor_date=date(2026, 5, 10),
    )
    assert rule.generate_from == date(2026, 5, 10)
    assert rule.id is not None


def test_update_rule_is_future_only_and_does_not_touch_past_expenses(
    db, recurring_rule_factory
):
    rule = recurring_rule_factory(
        amount_minor=10000,
        frequency="monthly",
        day_of_month=1,
        anchor_date=date(2026, 1, 1),
        generate_from=date(2026, 1, 1),
    )
    generate_due(db, rule, today=date(2026, 1, 1))
    original_expense = db.query(Expense).filter(Expense.source == "recurring").one()
    original_amount = original_expense.original_amount_minor

    update_rule(db, rule.id, amount_minor=20000)

    db.refresh(original_expense)
    assert original_expense.original_amount_minor == original_amount

    updated_rule = db.get(RecurringRule, rule.id)
    assert updated_rule.amount_minor == 20000


def test_pause_rule_generates_nothing_until_resumed(db, recurring_rule_factory):
    rule = recurring_rule_factory(
        frequency="monthly",
        day_of_month=1,
        anchor_date=date(2026, 1, 1),
        generate_from=date(2026, 1, 1),
    )
    pause_rule(db, rule.id)
    db.refresh(rule)
    assert rule.paused is True

    occurrences = generate_due(db, rule, today=date(2026, 3, 1))
    assert occurrences == []


def test_resume_rule_advances_generate_from_skipping_paused_window(
    db, recurring_rule_factory
):
    rule = recurring_rule_factory(
        frequency="monthly",
        day_of_month=1,
        anchor_date=date(2026, 1, 1),
        generate_from=date(2026, 1, 1),
        paused=True,
    )
    resume_today = date(2026, 5, 1)
    resume_rule(db, rule.id, today=resume_today)
    db.refresh(rule)

    assert rule.paused is False
    assert rule.generate_from == resume_today

    # The paused window (Jan-Apr) must never be backfilled.
    occurrences = generate_due(db, rule, today=date(2026, 5, 1))
    assert len(occurrences) == 1
    assert occurrences[0].period_key == "2026-05-01"


def test_delete_rule_removes_it(db, recurring_rule_factory):
    rule = recurring_rule_factory()
    rule_id = rule.id
    delete_rule(db, rule_id)
    assert db.get(RecurringRule, rule_id) is None


def test_list_rules_returns_only_owners_rules(db, recurring_rule_factory, seeded_users):
    user1, user2 = seeded_users
    recurring_rule_factory(owner_user_id=user1.id, merchant="Rent")
    recurring_rule_factory(owner_user_id=user2.id, merchant="Phone")

    rules = list_rules(db, user1.id)
    assert len(rules) == 1
    assert rules[0].merchant == "Rent"


def test_recurring_occurrence_unique_constraint_prevents_manual_duplicate(
    db, recurring_rule_factory
):
    rule = recurring_rule_factory()
    db.add(RecurringOccurrence(rule_id=rule.id, period_key="2026-01-01"))
    db.commit()

    db.add(RecurringOccurrence(rule_id=rule.id, period_key="2026-01-01"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
