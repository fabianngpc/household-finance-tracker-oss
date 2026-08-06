"""Tests for app/services/budget_alerts.py — deduplicated Telegram budget
alerts.

Headline test: crossing 80/100/120% of the user-TOTAL budget for the CURRENT
month enqueues exactly one alert per (owner, threshold, month) — no duplicate
spam on subsequent expenses. The `budget_alerts_sent` UNIQUE(user_id, period,
threshold) constraint (not application logic) arbitrates the dedup via
INSERT OR IGNORE + rowcount.
"""
from datetime import date

from app.models.budget import Budget, BudgetAlertSent
from app.models.notification import OutboundNotification
from app.services.budget_alerts import check_budget_alerts, _claim_alert
from app.services.expenses import create_expense_from_data


TODAY = date(2026, 7, 24)
PERIOD = f"{TODAY.year:04d}-{TODAY.month:02d}"


def _sent_rows(db, user_id, period=PERIOD):
    return (
        db.query(BudgetAlertSent)
        .filter_by(user_id=user_id, period=period)
        .all()
    )


def _outbound_rows(db):
    return db.query(OutboundNotification).all()


def _set_total_budget(db, user_id, amount_minor):
    db.add(Budget(user_id=user_id, category_id=None, amount_minor=amount_minor))
    db.commit()


def test_dedup_fires_once_per_threshold_across_saves(
    db, linked_user, seeded_categories, mock_frankfurter
):
    """Cross 80% -> 100% -> 120% via successive saves; each threshold alerts
    exactly once; more spend in the same month adds zero new rows."""
    user1 = linked_user
    category_id = seeded_categories[0].id
    _set_total_budget(db, user1.id, 200000)  # S$2000.00 cap

    # Cross exactly 80% (spend 1600.00 of a 2000.00 cap) with one expense.
    expense = create_expense_from_data(
        db, user1.id, "1600.00", "SGD", category_id, TODAY, source="web"
    )
    check_budget_alerts(db, user1.id, expense.occurred_on, today=TODAY)

    assert len(_sent_rows(db, user1.id)) == 1
    assert _sent_rows(db, user1.id)[0].threshold == 80
    assert len(_outbound_rows(db)) == 1
    body_80 = _outbound_rows(db)[0].body
    assert "⚠️ Budget check" in body_80
    assert "80%" in body_80

    # Re-check with no new spend -> no new rows (idempotent on repeated calls).
    check_budget_alerts(db, user1.id, expense.occurred_on, today=TODAY)
    assert len(_sent_rows(db, user1.id)) == 1
    assert len(_outbound_rows(db)) == 1

    # Cross exactly 100% (spend up to 2000.00 total).
    expense2 = create_expense_from_data(
        db, user1.id, "400.00", "SGD", category_id, TODAY, source="web"
    )
    check_budget_alerts(db, user1.id, expense2.occurred_on, today=TODAY)

    thresholds_sent = sorted(r.threshold for r in _sent_rows(db, user1.id))
    assert thresholds_sent == [80, 100]
    assert len(_outbound_rows(db)) == 2

    # Cross exactly 120% (spend up to 2400.00 total).
    expense3 = create_expense_from_data(
        db, user1.id, "400.00", "SGD", category_id, TODAY, source="web"
    )
    check_budget_alerts(db, user1.id, expense3.occurred_on, today=TODAY)

    thresholds_sent = sorted(r.threshold for r in _sent_rows(db, user1.id))
    assert thresholds_sent == [80, 100, 120]
    assert len(_outbound_rows(db)) == 3
    body_120 = next(o.body for o in _outbound_rows(db) if "120%" in o.body)
    assert "🔴 Over budget" in body_120

    # More spend in the same month -> zero new rows (all thresholds already sent).
    expense4 = create_expense_from_data(
        db, user1.id, "50.00", "SGD", category_id, TODAY, source="web"
    )
    check_budget_alerts(db, user1.id, expense4.occurred_on, today=TODAY)
    assert len(_sent_rows(db, user1.id)) == 3
    assert len(_outbound_rows(db)) == 3


def test_prior_month_never_alerts(db, linked_user, seeded_categories, mock_frankfurter):
    """occurred_on in a PRIOR month is a no-op even at 300% spend, no matter
    how much has been spent this month."""
    user1 = linked_user
    category_id = seeded_categories[0].id
    _set_total_budget(db, user1.id, 200000)

    # Expense dated last month; huge amount (300% of cap).
    prior_month = date(2026, 6, 15)
    expense = create_expense_from_data(
        db, user1.id, "6000.00", "SGD", category_id, prior_month, source="web"
    )

    check_budget_alerts(db, user1.id, expense.occurred_on, today=TODAY)

    assert _sent_rows(db, user1.id, period="2026-06") == []
    assert _sent_rows(db, user1.id, period=PERIOD) == []
    assert _outbound_rows(db) == []


def test_per_category_over_cap_never_alerts(db, linked_user, seeded_categories, mock_frankfurter):
    """A per-category budget being over-cap never alerts — only the
    user-TOTAL cap can trigger check_budget_alerts, and no total cap is set
    here."""
    user1 = linked_user
    category_id = seeded_categories[0].id
    # Per-category cap only (category_id NOT None) -- no total cap.
    db.add(Budget(user_id=user1.id, category_id=category_id, amount_minor=1000))
    db.commit()

    expense = create_expense_from_data(
        db, user1.id, "500.00", "SGD", category_id, TODAY, source="web"
    )
    check_budget_alerts(db, user1.id, expense.occurred_on, today=TODAY)

    assert _sent_rows(db, user1.id) == []
    assert _outbound_rows(db) == []


def test_no_budget_set_never_alerts(db, linked_user, seeded_categories, mock_frankfurter):
    """No total budget row at all -> check_budget_alerts is a no-op."""
    user1 = linked_user
    category_id = seeded_categories[0].id

    expense = create_expense_from_data(
        db, user1.id, "5000.00", "SGD", category_id, TODAY, source="web"
    )
    check_budget_alerts(db, user1.id, expense.occurred_on, today=TODAY)

    assert _sent_rows(db, user1.id) == []
    assert _outbound_rows(db) == []


def test_double_claim_is_race_safe(db, seeded_users):
    """Calling the low-level claim twice for the same (user, period,
    threshold) -> first returns True, second returns False (concurrency
    dedup proxy)."""
    user1, _ = seeded_users

    first = _claim_alert(db, user1.id, PERIOD, 80)
    second = _claim_alert(db, user1.id, PERIOD, 80)

    assert first is True
    assert second is False
    assert len(_sent_rows(db, user1.id)) == 1


def test_no_telegram_link_claims_but_does_not_enqueue(
    db, seeded_users, seeded_categories, mock_frankfurter
):
    """Owner with telegram_id None -> the sent-flag is still claimed (dedup
    holds) but NO outbound row is enqueued (lose, never duplicate)."""
    user1, user2 = seeded_users
    assert user2.telegram_id is None

    category_id = seeded_categories[0].id
    _set_total_budget(db, user2.id, 200000)

    expense = create_expense_from_data(
        db, user2.id, "1700.00", "SGD", category_id, TODAY, source="web"
    )
    check_budget_alerts(db, user2.id, expense.occurred_on, today=TODAY)

    assert len(_sent_rows(db, user2.id)) == 1
    assert _outbound_rows(db) == []


async def test_worker_drains_pending_outbound_notification(mock_bot, db, db_engine):
    """The worker's drain step claims a pending OutboundNotification, sends
    it via the Bot, and marks it sent."""
    from bot.worker import drain_outbound_notifications

    row = OutboundNotification(telegram_chat_id=555, body="Test alert body")
    db.add(row)
    db.commit()
    db.refresh(row)
    row_id = row.id

    count = await drain_outbound_notifications(mock_bot, lambda: db, db_engine)

    assert count == 1
    mock_bot.send_message.assert_awaited_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert call_kwargs["chat_id"] == 555
    assert call_kwargs["text"] == "Test alert body"

    fresh = db.get(OutboundNotification, row_id)
    assert fresh.status == "sent"
    assert fresh.sent_at is not None
