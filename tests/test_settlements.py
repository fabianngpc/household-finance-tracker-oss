"""Settlement recording/void invariant tests.

Invariant #9 — voiding a settlement is fully reversible: the balance reopens
to the exact prior figure, and the voided row still appears in the ledger
(list_settlements never hides history, it strikes it through).
"""

from datetime import date

from app.models.category import Category
from app.services.balance import compute_balance
from app.services.settlements import list_settlements, record_settlement, void_settlement
from app.services.shared_expenses import create_shared_expense


def _partner_category_id(db, user2):
    """Return a category id owned by user2, falling back to user1's if needed."""
    cat = db.query(Category).filter_by(user_id=user2.id).first()
    return cat.id


class TestVoidReversible:
    """Invariant #9 — voiding a settlement reopens the exact prior balance."""

    def test_void_reopens_exact_prior_balance(
        self, db, seeded_users, seeded_categories, mock_frankfurter
    ):
        user1, user2 = seeded_users
        cat1 = seeded_categories[0].id
        cat2 = _partner_category_id(db, user2)
        occurred_on = date(2026, 6, 15)

        # user1 pays SGD 100.00 split equally -> user2 owes user1 SGD 50.00
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

        bal_before_settle = compute_balance(db, user1.id, user2.id)
        assert bal_before_settle["SGD"] == 5000

        settlement = record_settlement(
            db, user2.id, user1.id, "50.00", "SGD", occurred_on
        )

        bal_settled = compute_balance(db, user1.id, user2.id)
        assert "SGD" not in bal_settled

        void_settlement(db, user1.id, settlement.id)

        bal_reopened = compute_balance(db, user1.id, user2.id)
        assert bal_reopened["SGD"] == 5000 == bal_before_settle["SGD"]

    def test_list_settlements_includes_voided(
        self, db, seeded_users, seeded_categories, mock_frankfurter
    ):
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
        settlement = record_settlement(
            db, user2.id, user1.id, "50.00", "SGD", occurred_on
        )
        void_settlement(db, user1.id, settlement.id)

        rows = list_settlements(db, user1.id, user2.id)
        assert len(rows) == 1
        assert rows[0].id == settlement.id
        assert rows[0].voided_at is not None
