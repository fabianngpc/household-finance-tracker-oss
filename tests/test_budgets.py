"""
Unit tests for the budgets service (CRUD + budget-vs-actual).

Behaviors covered:
- upsert_budget creates ONE total row per user and UPDATES it on a second call
  (never inserts a duplicate) — proves the ux_budget_total partial index holds.
- upsert_budget with category_id manages that category's cap independently of
  the total and of other categories.
- delete_budget removes only the targeted row (total vs a specific category).
- compute_budget_status reuses monthly_summary for the total spend (never
  re-aggregates from original amount + current FX) and computes correct
  pct/band for both the total cap and any per-category caps.
- budget_band boundaries: <80 healthy, 80..99 warning, >=100 over.
- Shared-expense attribution: each user's compute_budget_status counts ONLY
  their own share of a shared expense (no bespoke branching — this falls out
  of monthly_summary(user_id=owner) reading the per-user fan-out rows).
"""

from datetime import date

from app.models.budget import Budget
from app.models.category import Category
from app.services.budgets import (
    budget_band,
    compute_budget_status,
    delete_budget,
    get_total_budget,
    list_budgets,
    upsert_budget,
)
from app.services.expenses import create_expense_from_data
from app.services.shared_expenses import create_shared_expense


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_upsert_budget_total_creates_and_updates_single_row(db, seeded_users):
    """A second upsert_budget call on the same user's total cap UPDATES the
    existing row (one row total), it does not insert a duplicate."""
    user1, _ = seeded_users

    b1 = upsert_budget(db, user1.id, "2000")
    assert b1.amount_minor == 200000
    assert b1.category_id is None

    b2 = upsert_budget(db, user1.id, "2500")
    assert b2.id == b1.id
    assert b2.amount_minor == 250000

    rows = db.query(Budget).filter_by(user_id=user1.id, category_id=None).all()
    assert len(rows) == 1


def test_upsert_budget_category_independent(db, seeded_users, seeded_categories):
    """Per-category caps are independent rows, separate from the total cap."""
    user1, _ = seeded_users
    cat1_id = seeded_categories[0].id
    cat2_id = seeded_categories[1].id

    b1 = upsert_budget(db, user1.id, "300", category_id=cat1_id)
    b2 = upsert_budget(db, user1.id, "150", category_id=cat2_id)

    assert b1.id != b2.id
    assert get_total_budget(db, user1.id) is None

    rows = list_budgets(db, user1.id)
    assert len(rows) == 2

    # Updating cat1's cap again does not disturb cat2's row.
    upsert_budget(db, user1.id, "350", category_id=cat1_id)
    rows = {r.category_id: r.amount_minor for r in list_budgets(db, user1.id)}
    assert rows[cat1_id] == 35000
    assert rows[cat2_id] == 15000


def test_delete_budget_total_and_category_independently(db, seeded_users, seeded_categories):
    user1, _ = seeded_users
    cat_id = seeded_categories[0].id

    upsert_budget(db, user1.id, "2000")
    upsert_budget(db, user1.id, "300", category_id=cat_id)

    delete_budget(db, user1.id)  # deletes only the total
    assert get_total_budget(db, user1.id) is None
    remaining = list_budgets(db, user1.id)
    assert len(remaining) == 1
    assert remaining[0].category_id == cat_id

    delete_budget(db, user1.id, category_id=cat_id)
    assert list_budgets(db, user1.id) == []


def test_delete_budget_is_noop_when_absent(db, seeded_users):
    user1, _ = seeded_users
    delete_budget(db, user1.id)  # no total cap exists — must not raise
    delete_budget(db, user1.id, category_id=999999)


# ---------------------------------------------------------------------------
# budget_band boundaries
# ---------------------------------------------------------------------------


def test_budget_band_boundaries():
    assert budget_band(79) == "healthy"
    assert budget_band(80) == "warning"
    assert budget_band(99) == "warning"
    assert budget_band(100) == "over"
    assert budget_band(120) == "over"


# ---------------------------------------------------------------------------
# compute_budget_status — total cap bands
# ---------------------------------------------------------------------------


def test_compute_budget_status_warning_band(db, seeded_users, seeded_categories):
    user1, _ = seeded_users
    cat_id = seeded_categories[0].id

    upsert_budget(db, user1.id, "2000")  # cap 200000
    create_expense_from_data(db, user1.id, "1600.00", "SGD", cat_id, date(2026, 6, 10))

    status = compute_budget_status(db, user1.id, 2026, 6)

    assert status["total"]["cap_minor"] == 200000
    assert status["total"]["spent_minor"] == 160000
    assert status["total"]["pct"] == 80
    assert status["total"]["band"] == "warning"
    assert status["total"]["left_minor"] == 40000
    assert status["total"]["over_minor"] == 0


def test_compute_budget_status_over_band(db, seeded_users, seeded_categories):
    user1, _ = seeded_users
    cat_id = seeded_categories[0].id

    upsert_budget(db, user1.id, "2000")  # cap 200000
    create_expense_from_data(db, user1.id, "2400.00", "SGD", cat_id, date(2026, 6, 10))

    status = compute_budget_status(db, user1.id, 2026, 6)

    assert status["total"]["spent_minor"] == 240000
    assert status["total"]["pct"] == 120
    assert status["total"]["band"] == "over"
    assert status["total"]["left_minor"] == 0
    assert status["total"]["over_minor"] == 40000


def test_compute_budget_status_no_total_cap_lists_category_caps(db, seeded_users, seeded_categories):
    """No total cap set -> total is None, but per-category caps still show."""
    user1, _ = seeded_users
    cat_id = seeded_categories[0].id

    upsert_budget(db, user1.id, "300", category_id=cat_id)

    status = compute_budget_status(db, user1.id, 2026, 6)

    assert status["total"] is None
    assert len(status["categories"]) == 1
    cat_status = status["categories"][0]
    assert cat_status["category_id"] == cat_id
    assert cat_status["cap_minor"] == 30000
    assert cat_status["spent_minor"] == 0
    assert cat_status["pct"] == 0
    assert cat_status["band"] == "healthy"


def test_compute_budget_status_category_spend_and_band(db, seeded_users, seeded_categories):
    user1, _ = seeded_users
    cat_id = seeded_categories[0].id
    other_cat_id = seeded_categories[1].id

    upsert_budget(db, user1.id, "100", category_id=cat_id)
    create_expense_from_data(db, user1.id, "90.00", "SGD", cat_id, date(2026, 6, 5))
    # spend in a different, uncapped category must not bleed into cat_id's status
    create_expense_from_data(db, user1.id, "50.00", "SGD", other_cat_id, date(2026, 6, 6))

    status = compute_budget_status(db, user1.id, 2026, 6)

    cat_status = next(c for c in status["categories"] if c["category_id"] == cat_id)
    assert cat_status["cap_minor"] == 10000
    assert cat_status["spent_minor"] == 9000
    assert cat_status["pct"] == 90
    assert cat_status["band"] == "warning"
    assert cat_status["name"] == seeded_categories[0].name


# ---------------------------------------------------------------------------
# Attribution — the core correctness requirement
# ---------------------------------------------------------------------------


def test_shared_expense_attribution_counts_own_share_only(db, seeded_users, seeded_categories):
    """A shared 50/50 S$100 expense: each party's compute_budget_status counts
    ONLY their own half (5000), never the full 10000 — no special-casing
    needed, this falls out of monthly_summary(user_id=owner) reading the
    per-user fan-out rows written by create_shared_expense."""
    user1, user2 = seeded_users
    cat1_id = seeded_categories[0].id
    cat2_id = db.query(Category).filter_by(user_id=user2.id).first().id

    create_shared_expense(
        db,
        payer_id=user1.id,
        partner_id=user2.id,
        amount_str="100.00",
        currency="SGD",
        occurred_on=date(2026, 6, 15),
        split_method="equal",
        payer_category_id=cat1_id,
        partner_category_id=cat2_id,
        split_input={},
    )

    # Give both a total cap so we can read spent_minor via compute_budget_status.
    upsert_budget(db, user1.id, "1000")
    upsert_budget(db, user2.id, "1000")

    status1 = compute_budget_status(db, user1.id, 2026, 6)
    status2 = compute_budget_status(db, user2.id, 2026, 6)

    assert status1["total"]["spent_minor"] == 5000
    assert status2["total"]["spent_minor"] == 5000
    assert status1["total"]["spent_minor"] != 10000
    assert status2["total"]["spent_minor"] != 10000
