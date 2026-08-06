"""Invariant #1 — allocate_shares splits any integer total into shares that sum
EXACTLY to the total, across equal / percent / skewed weights and 0-dp / 2-dp
currencies.

Invariants #2, #3, #4 cover the create_shared_expense fan-out
write path: split-precondition rejection, no double-counting of shared money
in per-user reports, and header total == sum of the two linked children.
"""

import random
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.category import Category
from app.models.expense import Expense
from app.models.shared_expense import SharedExpense
from app.services import reports as reports_service
from app.services.expenses import delete_expense
from app.services.money import allocate_shares
from app.services.shared_expenses import (
    create_shared_expense,
    delete_shared_expense,
)


class TestAllocateShares:
    def test_equal_and_skewed_sum_exactly(self):
        random.seed(1234)
        totals = [1, 2, 3]  # explicit edge cases, always included
        for _ in range(2000):
            bucket = random.choice(["small", "large", "skewed"])
            if bucket == "small":
                total = random.choice(totals)
            else:
                total = random.randint(100, 500000)

            if bucket == "skewed":
                weights = [Decimal(1), Decimal(99)]
            else:
                w1 = random.randint(1, 100)
                w2 = random.randint(1, 100)
                weights = [Decimal(w1), Decimal(w2)]

            shares = allocate_shares(total, weights)
            assert sum(shares) == total
            assert len(shares) == 2
            assert all(s >= 0 for s in shares)

    def test_zero_dp_and_two_dp_identical_behavior(self):
        assert allocate_shares(1500, [Decimal(1), Decimal(1)]) == [750, 750]
        assert allocate_shares(10001, [Decimal(1), Decimal(1)]) == [5001, 5000]

    def test_bad_weights_raise(self):
        with pytest.raises(ValueError):
            allocate_shares(100, [])
        with pytest.raises(ValueError):
            allocate_shares(100, [Decimal(0), Decimal(1)])


def _partner_category_id(db, user2):
    """Return a category id owned by user2, falling back to user1's if needed."""
    cat = db.query(Category).filter_by(user_id=user2.id).first()
    return cat.id


class TestSplitPreconditions:
    """Invariant #2 — bad split inputs are rejected before any row is persisted."""

    def test_percent_not_100_raises(self, db, seeded_users, seeded_categories):
        user1, user2 = seeded_users
        cat1 = seeded_categories[0].id
        cat2 = _partner_category_id(db, user2)

        with pytest.raises(ValueError):
            create_shared_expense(
                db,
                user1.id,
                user2.id,
                "100.00",
                "SGD",
                date(2026, 6, 15),
                "percent",
                cat1,
                cat2,
                {"payer_pct": 60, "partner_pct": 45},
            )

    def test_exact_not_summing_raises(self, db, seeded_users, seeded_categories):
        user1, user2 = seeded_users
        cat1 = seeded_categories[0].id
        cat2 = _partner_category_id(db, user2)

        with pytest.raises(ValueError):
            create_shared_expense(
                db,
                user1.id,
                user2.id,
                "100.00",
                "SGD",
                date(2026, 6, 15),
                "exact",
                cat1,
                cat2,
                {"payer_minor": 5000, "partner_minor": 4999},
            )


class TestFanOut:
    """Invariant #4 — header total equals the sum of the two linked children."""

    def test_header_equals_sum_of_children(self, db, seeded_users, seeded_categories):
        user1, user2 = seeded_users
        cat1 = seeded_categories[0].id
        cat2 = _partner_category_id(db, user2)

        header, payer_row, partner_row = create_shared_expense(
            db,
            user1.id,
            user2.id,
            "100.01",
            "SGD",
            date(2026, 6, 15),
            "equal",
            cat1,
            cat2,
            {},
        )

        children = db.query(Expense).filter_by(shared_expense_id=header.id).all()
        assert len(children) == 2
        assert header.total_amount_minor == sum(c.original_amount_minor for c in children) == 10001
        shares = sorted(
            (c.original_amount_minor for c in children), reverse=True
        )
        assert shares == [5001, 5000]

    def test_children_linked_to_both_users(self, db, seeded_users, seeded_categories):
        user1, user2 = seeded_users
        cat1 = seeded_categories[0].id
        cat2 = _partner_category_id(db, user2)

        header, payer_row, partner_row = create_shared_expense(
            db,
            user1.id,
            user2.id,
            "50.00",
            "SGD",
            date(2026, 6, 15),
            "equal",
            cat1,
            cat2,
            {},
        )

        assert payer_row.user_id == user1.id
        assert partner_row.user_id == user2.id
        assert payer_row.shared_expense_id == header.id
        assert partner_row.shared_expense_id == header.id


class TestNoDoubleCount:
    """Invariant #3 — per-user reported spend does not double-count shared money."""

    def test_per_user_spend_no_double_count(self, db, seeded_users, seeded_categories):
        user1, user2 = seeded_users
        cat1 = seeded_categories[0].id
        cat2 = _partner_category_id(db, user2)

        occurred_on = date(2026, 6, 15)
        create_shared_expense(
            db,
            user1.id,
            user2.id,
            "100.00",
            "SGD",
            occurred_on,
            "equal",
            cat1,
            cat2,
            {},
        )

        mine = reports_service.monthly_summary(db, 2026, 6, user_id=user1.id)
        partner = reports_service.monthly_summary(db, 2026, 6, user_id=user2.id)
        combined = reports_service.monthly_summary(db, 2026, 6, user_id=None)

        assert (
            mine["total_sgd_minor"] + partner["total_sgd_minor"]
            == combined["total_sgd_minor"]
        )


LOGIN_URL = "/auth/login"
EXPENSES_URL = "/api/expenses"


def _login(client, username: str = "alice", password: str = "changeme"):
    resp = client.post(LOGIN_URL, json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp


class TestAtomicCascade:
    """Invariant #5 — edit/delete cascade is single-commit and atomic."""

    def test_exactly_two_children(self, db, seeded_users, seeded_categories):
        user1, user2 = seeded_users
        cat1 = seeded_categories[0].id
        cat2 = _partner_category_id(db, user2)

        header, _, _ = create_shared_expense(
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
        assert db.query(Expense).filter_by(shared_expense_id=header.id).count() == 2

    def test_forced_failure_leaves_zero_rows(
        self, db, seeded_users, seeded_categories, mocker
    ):
        user1, user2 = seeded_users
        cat1 = seeded_categories[0].id
        cat2 = _partner_category_id(db, user2)

        mocker.patch(
            "app.services.shared_expenses.compute_base_amount_minor",
            side_effect=[1, RuntimeError("boom")],
        )

        with pytest.raises(RuntimeError):
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

        # The forced failure happened after header.flush() but before commit —
        # simulate get_db's rollback-on-error teardown, then prove zero rows.
        db.rollback()
        assert db.query(SharedExpense).count() == 0
        assert (
            db.query(Expense).filter(Expense.shared_expense_id.isnot(None)).count()
            == 0
        )

    def test_delete_removes_all_three(self, db, seeded_users, seeded_categories):
        user1, user2 = seeded_users
        cat1 = seeded_categories[0].id
        cat2 = _partner_category_id(db, user2)

        header, _, _ = create_shared_expense(
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

        delete_shared_expense(db, user1.id, header.id)

        assert db.query(SharedExpense).count() == 0
        assert (
            db.query(Expense).filter(Expense.shared_expense_id.isnot(None)).count()
            == 0
        )


class TestSharedRowLock:
    """Invariant #11 — a money PATCH on a linked child row is rejected for
    BOTH the partner and the payer; category-only PATCH is still allowed."""

    def test_partner_cannot_patch_amount_but_can_recategorize(
        self, client, db, seeded_users, seeded_categories
    ):
        user1, user2 = seeded_users
        cat1 = seeded_categories[0].id
        cat2 = _partner_category_id(db, user2)

        header, payer_row, partner_row = create_shared_expense(
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

        _login(client, "partner", "changeme")

        resp = client.patch(
            f"{EXPENSES_URL}/{partner_row.id}", json={"amount": "999.00"}
        )
        assert 400 <= resp.status_code < 500, resp.text

        other_cat = (
            db.query(Category)
            .filter(Category.user_id == user2.id, Category.id != cat2)
            .first()
        )
        resp = client.patch(
            f"{EXPENSES_URL}/{partner_row.id}", json={"category_id": other_cat.id}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["category_id"] == other_cat.id

    def test_payer_cannot_patch_amount_but_can_recategorize(
        self, client, db, seeded_users, seeded_categories
    ):
        user1, user2 = seeded_users
        cat1 = seeded_categories[0].id
        cat2 = _partner_category_id(db, user2)

        header, payer_row, partner_row = create_shared_expense(
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

        _login(client, "alice", "changeme")

        resp = client.patch(
            f"{EXPENSES_URL}/{payer_row.id}", json={"amount": "999.00"}
        )
        assert 400 <= resp.status_code < 500, resp.text

        other_cat = (
            db.query(Category)
            .filter(Category.user_id == user1.id, Category.id != cat1)
            .first()
        )
        resp = client.patch(
            f"{EXPENSES_URL}/{payer_row.id}", json={"category_id": other_cat.id}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["category_id"] == other_cat.id


class TestSharedDeleteGuard:
    """Issue 1 (invariant #5 safety) — the generic delete_expense
    path refuses to delete a linked shared child, so no surface can orphan a
    header + partner row."""

    def test_generic_delete_of_child_rejected(
        self, db, seeded_users, seeded_categories
    ):
        user1, user2 = seeded_users
        cat1 = seeded_categories[0].id
        cat2 = _partner_category_id(db, user2)

        header, payer_row, partner_row = create_shared_expense(
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

        with pytest.raises(HTTPException) as exc_info:
            delete_expense(db, user1.id, payer_row.id)
        assert exc_info.value.status_code == 409

        assert db.query(SharedExpense).count() == 1
        assert (
            db.query(Expense).filter_by(shared_expense_id=header.id).count() == 2
        )


class TestExpenseOutExposesSharedId:
    """Wire-exposure data-path check — GET /api/expenses must carry a
    non-null shared_expense_id for shared child rows so the web table's
    routing gate can rely on it."""

    def test_get_expenses_includes_shared_expense_id(
        self, client, db, seeded_users, seeded_categories
    ):
        user1, user2 = seeded_users
        cat1 = seeded_categories[0].id
        cat2 = _partner_category_id(db, user2)

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

        _login(client, "alice", "changeme")
        client.post(
            EXPENSES_URL,
            json={
                "amount": "10.00",
                "currency": "SGD",
                "category_id": cat1,
                "occurred_on": "2026-06-16",
            },
        )

        resp = client.get(f"{EXPENSES_URL}?user=both")
        assert resp.status_code == 200, resp.text
        rows = resp.json()

        assert any(row["shared_expense_id"] is not None for row in rows)
        assert any(
            "shared_expense_id" in row and row["shared_expense_id"] is None
            for row in rows
        )
