"""Tests for app/services/capture.py — the capture state-machine service."""
import pytest

from app.models.capture import Capture
from app.models.job import Job


# ---------------------------------------------------------------------------
# Task 1: enqueue_capture, claim_next_job, complete_job
# ---------------------------------------------------------------------------

class TestEnqueueCapture:
    def test_enqueue_creates_capture_and_job(self, db, seeded_users):
        from app.services.capture import enqueue_capture

        user1, _ = seeded_users
        capture = enqueue_capture(
            db,
            update_id=1,
            telegram_user_id=111111111,
            telegram_chat_id=111111111,
            user_id=user1.id,
            raw_text="$12 lunch",
        )

        assert capture is not None
        assert capture.id is not None
        assert capture.status == "queued"
        assert capture.update_id == 1
        assert capture.user_id == user1.id

        # Exactly one Capture and one Job
        assert db.query(Capture).count() == 1
        job = db.query(Job).filter_by(capture_id=capture.id).first()
        assert job is not None
        assert job.status == "pending"

    def test_enqueue_with_image_path_persists_it(self, db, seeded_users):
        from app.services.capture import enqueue_capture

        user1, _ = seeded_users
        capture = enqueue_capture(
            db,
            update_id=101,
            telegram_user_id=111111111,
            telegram_chat_id=111111111,
            user_id=user1.id,
            raw_text="receipt photo",
            image_path="/tmp/receipt.jpg",
        )

        assert capture is not None
        assert capture.image_path == "/tmp/receipt.jpg"

    def test_enqueue_without_image_path_defaults_none(self, db, seeded_users):
        from app.services.capture import enqueue_capture

        user1, _ = seeded_users
        capture = enqueue_capture(
            db,
            update_id=102,
            telegram_user_id=111111111,
            telegram_chat_id=111111111,
            user_id=user1.id,
            raw_text="just text",
        )

        assert capture is not None
        assert capture.image_path is None

    def test_enqueue_idempotent_duplicate_returns_none(self, db, seeded_users):
        from app.services.capture import enqueue_capture

        user1, _ = seeded_users
        first = enqueue_capture(
            db,
            update_id=42,
            telegram_user_id=111111111,
            telegram_chat_id=111111111,
            user_id=user1.id,
            raw_text="$12 lunch",
        )
        assert first is not None

        second = enqueue_capture(
            db,
            update_id=42,  # same update_id
            telegram_user_id=111111111,
            telegram_chat_id=111111111,
            user_id=user1.id,
            raw_text="$12 lunch again",
        )

        assert second is None
        # Still only one capture and one job
        assert db.query(Capture).count() == 1
        assert db.query(Job).count() == 1


class TestClaimNextJob:
    def test_claim_returns_job_and_capture_ids(self, db, db_engine, capture_factory, job_factory):
        from app.services.capture import claim_next_job

        capture = capture_factory()
        job = job_factory(capture.id, status="pending")
        db.commit()

        result = claim_next_job(db_engine)

        assert result is not None
        assert result["job_id"] == job.id
        assert result["capture_id"] == capture.id

    def test_claim_sets_job_status_to_processing(self, db, db_engine, capture_factory, job_factory):
        from app.services.capture import claim_next_job

        capture = capture_factory()
        job = job_factory(capture.id, status="pending")
        db.commit()

        claim_next_job(db_engine)

        db.expire(job)
        db.refresh(job)
        assert job.status == "processing"

    def test_claim_returns_none_when_no_pending_jobs(self, db_engine):
        from app.services.capture import claim_next_job

        result = claim_next_job(db_engine)
        assert result is None

    def test_claim_does_not_return_already_claimed_job(self, db, db_engine, capture_factory, job_factory):
        from app.services.capture import claim_next_job

        capture1 = capture_factory()
        job_factory(capture1.id, status="pending")
        capture2 = capture_factory()
        job_factory(capture2.id, status="pending")
        db.commit()

        first = claim_next_job(db_engine)
        second = claim_next_job(db_engine)
        assert first is not None
        assert second is not None
        assert first["job_id"] != second["job_id"]

    def test_claim_returns_none_after_all_jobs_claimed(self, db, db_engine, capture_factory, job_factory):
        from app.services.capture import claim_next_job

        capture = capture_factory()
        job_factory(capture.id, status="pending")
        db.commit()

        claim_next_job(db_engine)
        result = claim_next_job(db_engine)
        assert result is None


class TestCompleteJob:
    def test_complete_job_sets_status_done(self, db, capture_factory, job_factory):
        from app.services.capture import complete_job

        capture = capture_factory()
        job = job_factory(capture.id, status="processing")

        complete_job(db, job.id, "done")

        db.refresh(job)
        assert job.status == "done"

    def test_complete_job_sets_status_failed_with_error(self, db, capture_factory, job_factory):
        from app.services.capture import complete_job

        capture = capture_factory()
        job = job_factory(capture.id, status="processing")

        complete_job(db, job.id, "failed", error="something went wrong")

        db.refresh(job)
        assert job.status == "failed"
        assert job.error == "something went wrong"


# ---------------------------------------------------------------------------
# Task 2: process_capture, save_capture_expense, resolve_other_category_id,
#          apply_confirm_input
# ---------------------------------------------------------------------------

class TestResolveOtherCategoryId:
    def test_returns_protected_other_category_id(self, db, linked_user, seeded_categories):
        from app.services.capture import resolve_other_category_id
        from app.models.category import Category

        cat_id = resolve_other_category_id(db, linked_user.id)

        cat = db.get(Category, cat_id)
        assert cat is not None
        assert cat.name == "Other"
        assert cat.is_protected == 1

    def test_raises_value_error_if_missing(self, db):
        from app.services.capture import resolve_other_category_id

        with pytest.raises(ValueError, match="Other"):
            resolve_other_category_id(db, user_id=99999)


class TestProcessCapture:
    def test_high_confidence_saves_expense(self, db, db_engine, linked_user, seeded_categories, capture_factory, mock_frankfurter):
        from datetime import date
        from app.services.capture import process_capture
        from app.models.expense import Expense
        from bot.extractor import ExtractionResult

        capture = capture_factory(user_id=linked_user.id)
        result = ExtractionResult(
            amount_str="12",
            currency="SGD",
            merchant="lunch",
            expense_date=date.today(),
            category_hint="Other",
            confidence=1.0,
        )

        returned = process_capture(db, capture, result)

        assert returned.status == "done"
        assert returned.expense_id is not None

        expenses = db.query(Expense).filter_by(user_id=linked_user.id).all()
        assert len(expenses) == 1
        exp = expenses[0]
        assert exp.source == "telegram"
        assert exp.original_currency == "SGD"
        assert exp.merchant == "lunch"

    def test_high_confidence_uses_other_category(self, db, db_engine, linked_user, seeded_categories, capture_factory, mock_frankfurter):
        from datetime import date
        from app.services.capture import process_capture, resolve_other_category_id
        from app.models.expense import Expense
        from bot.extractor import ExtractionResult

        capture = capture_factory(user_id=linked_user.id)
        result = ExtractionResult(
            amount_str="5",
            currency="SGD",
            merchant="coffee",
            expense_date=date.today(),
            category_hint="Other",
            confidence=1.0,
        )
        process_capture(db, capture, result)

        exp = db.query(Expense).filter_by(user_id=linked_user.id).first()
        other_cat_id = resolve_other_category_id(db, linked_user.id)
        assert exp.category_id == other_cat_id

    def test_low_confidence_parks_pending_confirm(self, db, db_engine, linked_user, seeded_categories, capture_factory):
        from datetime import date
        from app.services.capture import process_capture
        from app.models.expense import Expense
        from bot.extractor import ExtractionResult

        capture = capture_factory(user_id=linked_user.id)
        result = ExtractionResult(
            amount_str=None,
            currency="SGD",
            merchant="lunch somewhere",
            expense_date=date.today(),
            category_hint="Other",
            confidence=0.0,
        )

        returned = process_capture(db, capture, result)

        assert returned.status == "pending_confirm"
        assert returned.confirm_step == "amount"
        assert db.query(Expense).count() == 0


class TestApplyConfirmInput:
    def test_valid_amount_completes_save(self, db, linked_user, seeded_categories, capture_factory, mock_frankfurter):
        from datetime import date
        from app.services.capture import apply_confirm_input
        from app.models.expense import Expense

        capture = capture_factory(
            user_id=linked_user.id,
            status="pending_confirm",
            confirm_step="amount",
            currency="SGD",
            merchant="test merchant",
            expense_date=date.today().isoformat(),
        )

        returned = apply_confirm_input(db, capture, "12")

        assert returned.status == "done"
        assert returned.confirm_step == "post_save"
        assert returned.expense_id is not None
        assert db.query(Expense).filter_by(user_id=linked_user.id).count() == 1

    def test_invalid_amount_leaves_pending(self, db, linked_user, seeded_categories, capture_factory):
        from datetime import date
        from app.services.capture import apply_confirm_input
        from app.models.expense import Expense

        capture = capture_factory(
            user_id=linked_user.id,
            status="pending_confirm",
            confirm_step="amount",
            currency="SGD",
            merchant="test merchant",
            expense_date=date.today().isoformat(),
        )

        returned = apply_confirm_input(db, capture, "abc")

        assert returned.status == "pending_confirm"
        assert returned.confirm_step == "amount"
        assert returned.error is not None
        assert returned.error != ""
        assert db.query(Expense).count() == 0

    def test_reedit_updates_existing_expense_in_place(
        self, db, linked_user, seeded_categories, capture_factory, mock_frankfurter
    ):
        """Re-editing the amount of an already-saved expense must UPDATE the
        same row, not INSERT a duplicate (money double-count regression)."""
        from datetime import date
        from app.services.capture import apply_confirm_input
        from app.models.expense import Expense
        from app.services.expenses import create_expense_from_data

        other_cat = next(c for c in seeded_categories if c.name == "Other")
        original = create_expense_from_data(
            db,
            user_id=linked_user.id,
            amount_str="50",
            currency="SGD",
            category_id=other_cat.id,
            expense_date=date(2026, 6, 29),
            merchant="lunch",
            source="telegram",
        )
        original_id = original.id

        # A post_save capture pointing at that expense, re-opened to edit amount.
        capture = capture_factory(
            user_id=linked_user.id,
            status="pending_confirm",
            confirm_step="amount",
            expense_id=original_id,
            currency="SGD",
            merchant="lunch",
            expense_date="2026-06-29",
        )

        returned = apply_confirm_input(db, capture, "45")

        # Exactly ONE expense row for this user — no duplicate created.
        assert db.query(Expense).filter_by(user_id=linked_user.id).count() == 1
        # Same expense id preserved, amount updated in place.
        updated = db.query(Expense).filter_by(id=original_id).first()
        assert updated is not None
        assert updated.original_amount_minor == 4500
        # Capture stays linked to the same expense and returns to post_save.
        assert returned.expense_id == original_id
        assert returned.status == "done"
        assert returned.confirm_step == "post_save"

    def test_reedit_refuses_shared_expense(
        self, db, linked_user, seeded_users, seeded_categories, capture_factory, mock_frankfurter
    ):
        """A re-edit whose linked expense is a shared child must not mutate or
        duplicate it — apply_confirm_input leaves it untouched."""
        from datetime import date
        from app.services.capture import apply_confirm_input
        from app.models.expense import Expense
        from app.models.category import Category
        from app.services.shared_expenses import create_shared_expense

        user1, user2 = seeded_users  # linked_user == user1
        cat1 = seeded_categories[0].id
        cat2 = db.query(Category).filter_by(user_id=user2.id).first().id

        _, payer_row, _ = create_shared_expense(
            db, user1.id, user2.id, "30.00", "SGD", date(2026, 6, 21), "equal", cat1, cat2, {}
        )
        payer_id = payer_row.id
        original_minor = payer_row.original_amount_minor
        before_count = db.query(Expense).count()

        capture = capture_factory(
            user_id=user1.id,
            status="pending_confirm",
            confirm_step="amount",
            expense_id=payer_id,
            currency="SGD",
            merchant=None,
            expense_date="2026-06-21",
        )

        apply_confirm_input(db, capture, "45")

        # No new row; the shared child's amount is unchanged.
        assert db.query(Expense).count() == before_count
        refreshed = db.query(Expense).filter_by(id=payer_id).first()
        assert refreshed.original_amount_minor == original_minor


class TestSaveCaptureExpense:
    def test_saves_expense_with_telegram_source(self, db, linked_user, seeded_categories, capture_factory, mock_frankfurter):
        from datetime import date
        from app.services.capture import save_capture_expense
        from app.models.expense import Expense

        today = date.today()
        capture = capture_factory(
            user_id=linked_user.id,
            amount_str="8.50",
            currency="SGD",
            merchant="hawker",
            expense_date=today.isoformat(),
        )

        expense = save_capture_expense(db, capture)

        assert expense.source == "telegram"
        assert expense.merchant == "hawker"
        assert expense.original_currency == "SGD"
        assert expense.occurred_on == today

    def test_uses_expense_date_not_system_clock(self, db, linked_user, seeded_categories, capture_factory, mock_frankfurter):
        from app.services.capture import save_capture_expense
        from app.models.expense import Expense

        fixed_date = "2026-01-15"
        capture = capture_factory(
            user_id=linked_user.id,
            amount_str="10",
            currency="SGD",
            merchant="test",
            expense_date=fixed_date,
        )

        expense = save_capture_expense(db, capture)

        from datetime import date
        assert expense.occurred_on == date.fromisoformat(fixed_date)

    def test_defaults_currency_to_sgd_when_none(self, db, linked_user, seeded_categories, capture_factory, mock_frankfurter):
        from datetime import date
        from app.services.capture import save_capture_expense
        from app.models.expense import Expense

        capture = capture_factory(
            user_id=linked_user.id,
            amount_str="5",
            currency=None,
            merchant="test",
            expense_date=date.today().isoformat(),
        )

        expense = save_capture_expense(db, capture)

        assert expense.original_currency == "SGD"
