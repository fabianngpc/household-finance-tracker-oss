"""Tests for scripts/retry_failed_captures.py — the FX-failure backfill.

Verifies the backfill re-drives a failed, never-saved IDR capture into a real
expense, queues a recovery notification, respects --dry-run, and refuses to
touch a capture that already produced an expense (no double-count).
"""
from unittest.mock import MagicMock

from app.models.capture import Capture
from app.models.expense import Expense
from app.models.notification import OutboundNotification
from scripts.retry_failed_captures import find_retryable, retry_failed_captures


def _mock_idr_fx(mocker):
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "amount": 1.0,
        "base": "SGD",
        "date": "2026-06-27",
        "rates": {"USD": 0.74, "IDR": 13934, "THB": 25.86},
    }
    return mocker.patch("httpx.get", return_value=fake_response)


def _failed_idr_capture(capture_factory, user_id, category_id):
    """A capture in the exact state an FX failure leaves behind: fields set,
    status 'failed', no expense ever created."""
    return capture_factory(
        user_id=user_id,
        raw_message="lunch 90000 IDR",
        status="failed",
        amount_str="90000",
        currency="IDR",
        merchant="Warung",
        expense_date="2026-06-27",
        category_id=category_id,
        expense_id=None,
    )


def test_recovers_failed_idr_capture_and_notifies(
    db, linked_user, seeded_categories, capture_factory, mocker
):
    _mock_idr_fx(mocker)
    cat_id = seeded_categories[0].id
    capture = _failed_idr_capture(capture_factory, linked_user.id, cat_id)
    capture_id = capture.id

    summary = retry_failed_captures(db, dry_run=False, notify=True)

    assert summary == {"candidates": 1, "recovered": 1, "still_failed": 0}

    fresh = db.get(Capture, capture_id)
    assert fresh.status == "done"
    assert fresh.expense_id is not None

    expenses = db.query(Expense).filter_by(user_id=linked_user.id).all()
    assert len(expenses) == 1

    notes = db.query(OutboundNotification).all()
    assert len(notes) == 1
    assert notes[0].telegram_chat_id == capture.telegram_chat_id
    assert "90000" in notes[0].body


def test_dry_run_changes_nothing(
    db, linked_user, seeded_categories, capture_factory, mocker
):
    mock_get = _mock_idr_fx(mocker)
    cat_id = seeded_categories[0].id
    capture = _failed_idr_capture(capture_factory, linked_user.id, cat_id)
    capture_id = capture.id

    summary = retry_failed_captures(db, dry_run=True, notify=True)

    assert summary["candidates"] == 1
    assert summary["recovered"] == 0

    fresh = db.get(Capture, capture_id)
    assert fresh.status == "failed"
    assert fresh.expense_id is None
    assert db.query(Expense).count() == 0
    assert db.query(OutboundNotification).count() == 0
    mock_get.assert_not_called()  # no FX network call in dry-run


def test_already_saved_capture_is_not_retried(
    db, linked_user, seeded_categories, capture_factory, mocker
):
    """A failed row that already has an expense_id must be skipped — retrying
    it would insert a second expense and double-count the money."""
    _mock_idr_fx(mocker)
    cat_id = seeded_categories[0].id
    capture = capture_factory(
        user_id=linked_user.id,
        raw_message="lunch 90000 IDR",
        status="failed",
        amount_str="90000",
        currency="IDR",
        expense_date="2026-06-27",
        category_id=cat_id,
        expense_id=424242,  # already linked to an expense
    )

    assert find_retryable(db) == []
    summary = retry_failed_captures(db, dry_run=False, notify=True)
    assert summary["candidates"] == 0
    assert db.query(Expense).count() == 0
