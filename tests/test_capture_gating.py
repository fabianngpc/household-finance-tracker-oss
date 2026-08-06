"""Tests for per-field confidence gating and category hint resolution.

Uses FakeExtractor + make_result from tests/fakes.py — zero real model calls in CI.
"""
import pytest
from datetime import date

from tests.fakes import FakeExtractor, make_result


# ---------------------------------------------------------------------------
# Task 1: resolve_category_for_hint
# ---------------------------------------------------------------------------


class TestResolveCategoryForHint:
    def test_category_hint_resolves_known(self, db, seeded_users):
        """Known hint resolves to the matching category id."""
        from app.services.categories import resolve_category_for_hint
        from app.models.category import Category

        user1, _ = seeded_users
        groceries = db.query(Category).filter_by(user_id=user1.id, name="Groceries").first()

        result = resolve_category_for_hint(db, user1.id, "Groceries")
        assert result == groceries.id

    def test_category_hint_resolves_case_insensitive(self, db, seeded_users):
        """Hint matching is case-insensitive ('groceries' → Groceries id)."""
        from app.services.categories import resolve_category_for_hint
        from app.models.category import Category

        user1, _ = seeded_users
        groceries = db.query(Category).filter_by(user_id=user1.id, name="Groceries").first()

        result = resolve_category_for_hint(db, user1.id, "groceries")
        assert result == groceries.id

    def test_category_hint_resolves_unknown_to_other(self, db, seeded_users):
        """Unknown hint ('Spaceship') falls back to the protected 'Other' category id."""
        from app.services.categories import resolve_category_for_hint, resolve_other_category_id

        user1, _ = seeded_users
        other_id = resolve_other_category_id(db, user1.id)

        result = resolve_category_for_hint(db, user1.id, "Spaceship")
        assert result == other_id

    def test_category_hint_resolves_none_to_other(self, db, seeded_users):
        """None hint falls back to the protected 'Other' category id."""
        from app.services.categories import resolve_category_for_hint, resolve_other_category_id

        user1, _ = seeded_users
        other_id = resolve_other_category_id(db, user1.id)

        result = resolve_category_for_hint(db, user1.id, None)
        assert result == other_id

    def test_category_hint_user_isolation(self, db, seeded_users):
        """Hint resolves only within the given user's categories — never crosses user boundary."""
        from app.services.categories import resolve_category_for_hint
        from app.models.category import Category

        user1, user2 = seeded_users
        user1_groceries = db.query(Category).filter_by(user_id=user1.id, name="Groceries").first()
        user2_groceries = db.query(Category).filter_by(user_id=user2.id, name="Groceries").first()

        assert user1_groceries.id != user2_groceries.id

        result1 = resolve_category_for_hint(db, user1.id, "Groceries")
        result2 = resolve_category_for_hint(db, user2.id, "Groceries")
        assert result1 == user1_groceries.id
        assert result2 == user2_groceries.id
        assert result1 != result2


# ---------------------------------------------------------------------------
# Task 2: Confidence-driven process_capture + category-aware save
# ---------------------------------------------------------------------------


class TestProcessCaptureConfidenceGating:
    def test_high_amount_confidence_auto_saves(
        self, db, linked_user, seeded_categories, capture_factory, mock_frankfurter
    ):
        """Amount-confident result (confidence_amount ≥ 0.7) auto-saves immediately."""
        from app.services.capture import process_capture
        from app.models.expense import Expense

        capture = capture_factory(user_id=linked_user.id)
        result = make_result(
            amount_str="10.00",
            confidence_amount=0.9,
            confidence_category=0.0,
        )

        returned = process_capture(db, capture, result)

        assert returned.status == "done"
        assert returned.expense_id is not None
        assert db.query(Expense).filter_by(user_id=linked_user.id).count() == 1

    def test_low_amount_confidence_parks_pending_confirm(
        self, db, linked_user, seeded_categories, capture_factory
    ):
        """Amount-low-confidence (<0.7) parks capture for single-step amount confirm."""
        from app.services.capture import process_capture
        from app.models.expense import Expense

        capture = capture_factory(user_id=linked_user.id)
        result = make_result(
            amount_str=None,
            confidence_amount=0.5,
            confidence_category=0.0,
        )

        returned = process_capture(db, capture, result)

        assert returned.status == "pending_confirm"
        assert returned.confirm_step == "amount"
        assert db.query(Expense).count() == 0

    def test_confident_category_resolves_to_groceries(
        self, db, linked_user, seeded_categories, capture_factory, mock_frankfurter
    ):
        """High confidence_category + known hint → saved expense carries Groceries id."""
        from app.services.capture import process_capture
        from app.services.categories import resolve_category_for_hint
        from app.models.expense import Expense

        capture = capture_factory(user_id=linked_user.id)
        result = make_result(
            amount_str="42.00",
            category_hint="Groceries",
            confidence_amount=0.9,
            confidence_category=0.8,
        )

        process_capture(db, capture, result)

        exp = db.query(Expense).filter_by(user_id=linked_user.id).first()
        groceries_id = resolve_category_for_hint(db, linked_user.id, "Groceries")
        assert exp.category_id == groceries_id

    def test_low_confidence_category_falls_back_to_other(
        self, db, linked_user, seeded_categories, capture_factory, mock_frankfurter
    ):
        """Low confidence_category → 'Other' id, no 'category' confirm step added."""
        from app.services.capture import process_capture
        from app.services.categories import resolve_other_category_id
        from app.models.expense import Expense

        capture = capture_factory(user_id=linked_user.id)
        result = make_result(
            amount_str="10.00",
            category_hint="Groceries",
            confidence_amount=0.9,
            confidence_category=0.2,
        )

        returned = process_capture(db, capture, result)

        exp = db.query(Expense).filter_by(user_id=linked_user.id).first()
        other_id = resolve_other_category_id(db, linked_user.id)
        assert exp.category_id == other_id
        assert returned.confirm_step != "category"

    def test_legacy_stub_result_auto_saves(
        self, db, linked_user, seeded_categories, capture_factory, mock_frankfurter
    ):
        """Legacy StubExtractor-shaped result (confidence=1.0, confidence_amount=None) still auto-saves."""
        from app.services.capture import process_capture
        from app.models.expense import Expense
        from bot.extractor import ExtractionResult

        capture = capture_factory(user_id=linked_user.id)
        result = ExtractionResult(
            amount_str="12.50",
            currency="SGD",
            merchant="hawker",
            expense_date=date.today(),
            category_hint="Other",
            confidence=1.0,
            # confidence_amount is None (backward-compat with StubExtractor)
        )

        returned = process_capture(db, capture, result)

        assert returned.status == "done"
        assert db.query(Expense).filter_by(user_id=linked_user.id).count() == 1
