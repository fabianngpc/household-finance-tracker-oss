"""Derived balance invariant tests.

The balance is derived from split rows minus settlement rows, per currency,
and must never be a stored mutable number.

Invariant #7 — per-currency independence: settling one currency never
affects another.
Invariant #8 — FX is never baked into a debt: a later FX-rate change must
never alter a previously computed balance (reads original_amount_minor /
original_currency, not amount_base_minor).
"""

import random
from datetime import date

from app.models.category import Category
from app.models.expense import Expense
from app.models.fx_rate import FxRate
from app.models.settlement import Settlement
from app.models.shared_expense import SharedExpense
from app.services.balance import compute_balance
from app.services.money import format_from_minor_units, parse_to_minor_units
from app.services.settlements import record_settlement, void_settlement
from app.services.shared_expenses import (
    create_shared_expense,
    delete_shared_expense,
    update_shared_expense,
)


def _partner_category_id(db, user2):
    """Return a category id owned by user2, falling back to user1's if needed."""
    cat = db.query(Category).filter_by(user_id=user2.id).first()
    return cat.id


class TestPerCurrencyIndependence:
    """Invariant #7 — settling one currency does not touch another."""

    def test_two_currencies_independent_and_partial_settle(
        self, db, seeded_users, seeded_categories, mock_frankfurter
    ):
        user1, user2 = seeded_users
        cat1 = seeded_categories[0].id
        cat2 = _partner_category_id(db, user2)
        occurred_on = date(2026, 6, 15)

        # user1 pays a EUR expense split equally -> user2 owes user1 EUR 50.00
        create_shared_expense(
            db,
            user1.id,
            user2.id,
            "100.00",
            "EUR",
            occurred_on,
            "equal",
            cat1,
            cat2,
            {},
        )
        # user2 pays a USD expense split equally -> user1 owes user2 USD 30.00
        create_shared_expense(
            db,
            user2.id,
            user1.id,
            "60.00",
            "USD",
            occurred_on,
            "equal",
            cat2,
            cat1,
            {},
        )

        bal = compute_balance(db, user1.id, user2.id)
        assert bal["EUR"] == 5000
        assert bal["USD"] == -3000

        # Fully clear the EUR balance: user2 pays user1 EUR 50.00
        record_settlement(
            db, user2.id, user1.id, "50.00", "EUR", occurred_on
        )

        bal_after = compute_balance(db, user1.id, user2.id)
        assert "EUR" not in bal_after
        assert bal_after["USD"] == -3000


class TestFxNotBakedIn:
    """Invariant #8 — a later FX-rate change never alters a previously
    computed balance; balance always reads original_amount_minor/currency."""

    def test_new_fx_rate_row_does_not_change_balance(
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
            "EUR",
            occurred_on,
            "equal",
            cat1,
            cat2,
            {},
        )

        bal_before = compute_balance(db, user1.id, user2.id)
        assert bal_before["EUR"] == 5000  # partner's half of EUR 100.00

        # Insert a new FX rate row for a LATER date with a very different rate.
        db.add(
            FxRate(
                base_currency="SGD",
                quote_currency="EUR",
                rate=999.0,
                as_of_date=date(2026, 12, 31),
            )
        )
        db.commit()

        bal_after = compute_balance(db, user1.id, user2.id)
        assert bal_after["EUR"] == bal_before["EUR"] == 5000


def _recompute_from_scratch(db, a: int, b: int) -> dict[str, int]:
    """Independent, structurally-different balance recomputation using plain
    Python loops over ORM rows (NOT the same SQL aggregate query compute_balance
    uses) — a second implementation to catch bugs in the query itself.

    Mirrors compute_balance's sign convention: positive means b owes a.
    """
    bal: dict[str, int] = {}

    for header in db.query(SharedExpense).all():
        if header.payer_user_id not in (a, b):
            continue
        children = db.query(Expense).filter_by(shared_expense_id=header.id).all()
        for child in children:
            if child.user_id == header.payer_user_id:
                continue  # the payer's own share never creates a debt
            currency = child.original_currency
            amt = child.original_amount_minor
            if header.payer_user_id == a and child.user_id == b:
                bal[currency] = bal.get(currency, 0) + amt
            elif header.payer_user_id == b and child.user_id == a:
                bal[currency] = bal.get(currency, 0) - amt

    for s in db.query(Settlement).filter(Settlement.voided_at.is_(None)).all():
        if s.from_user_id == a and s.to_user_id == b:
            bal[s.currency] = bal.get(s.currency, 0) + s.amount_minor
        elif s.from_user_id == b and s.to_user_id == a:
            bal[s.currency] = bal.get(s.currency, 0) - s.amount_minor

    return {c: n for c, n in bal.items() if n != 0}


def _valid_split_input(method: str, total_minor: int) -> dict:
    """Build a valid split_input for the given method/total for property tests."""
    if method == "equal":
        return {}
    elif method == "percent":
        p = random.randint(1, 99)
        q = 100 - p
        return {"payer_pct": p, "partner_pct": q}
    elif method == "exact":
        payer_minor = random.randint(0, total_minor)
        partner_minor = total_minor - payer_minor
        return {"payer_minor": payer_minor, "partner_minor": partner_minor}
    raise ValueError(f"Unknown split_method: {method!r}")


class TestDerivedBalanceReplay:
    """Invariant #6 — compute_balance matches an independent from-scratch
    recomputation after any random create/edit/delete/settle/void sequence."""

    def test_replay_random_sequence(
        self, db, seeded_users, seeded_categories, mock_frankfurter
    ):
        random.seed(20260706)
        user1, user2 = seeded_users
        cat1 = seeded_categories[0].id
        cat2 = _partner_category_id(db, user2)
        currencies = ["SGD", "EUR", "USD"]
        methods = ["equal", "percent", "exact"]
        occurred_on = date(2026, 6, 15)

        for _sequence in range(30):
            headers: dict[int, dict] = {}  # header_id -> payer_id/currency/method
            active_settlements: list[int] = []

            n_ops = random.randint(5, 20)
            for _op_idx in range(n_ops):
                op = random.choice(["create", "edit", "delete", "settle", "void"])

                if op == "create":
                    payer, partner = (
                        (user1, user2) if random.random() < 0.5 else (user2, user1)
                    )
                    currency = random.choice(currencies)
                    method = random.choice(methods)
                    total_minor = random.randint(100, 100000)
                    amount_str = format_from_minor_units(total_minor, currency)
                    total_minor = parse_to_minor_units(amount_str, currency)
                    split_input = _valid_split_input(method, total_minor)

                    header, _, _ = create_shared_expense(
                        db,
                        payer.id,
                        partner.id,
                        amount_str,
                        currency,
                        occurred_on,
                        method,
                        cat1,
                        cat2,
                        split_input,
                    )
                    headers[header.id] = {
                        "payer_id": payer.id,
                        "currency": currency,
                        "method": method,
                    }

                elif op == "edit":
                    if not headers:
                        continue
                    header_id = random.choice(list(headers.keys()))
                    meta = headers[header_id]
                    total_minor = random.randint(100, 100000)
                    amount_str = format_from_minor_units(total_minor, meta["currency"])
                    total_minor = parse_to_minor_units(amount_str, meta["currency"])
                    split_input = _valid_split_input(meta["method"], total_minor)
                    update_shared_expense(
                        db,
                        meta["payer_id"],
                        header_id,
                        amount_str=amount_str,
                        split_input=split_input,
                    )

                elif op == "delete":
                    if not headers:
                        continue
                    header_id = random.choice(list(headers.keys()))
                    meta = headers.pop(header_id)
                    delete_shared_expense(db, meta["payer_id"], header_id)

                elif op == "settle":
                    from_user, to_user = (
                        (user1, user2) if random.random() < 0.5 else (user2, user1)
                    )
                    currency = random.choice(currencies)
                    amount_minor = random.randint(1, 50000)
                    amount_str = format_from_minor_units(amount_minor, currency)
                    settlement = record_settlement(
                        db, from_user.id, to_user.id, amount_str, currency, occurred_on
                    )
                    active_settlements.append(settlement.id)

                else:  # void
                    if not active_settlements:
                        continue
                    settlement_id = random.choice(active_settlements)
                    active_settlements.remove(settlement_id)
                    void_settlement(db, user1.id, settlement_id)

                assert compute_balance(
                    db, user1.id, user2.id
                ) == _recompute_from_scratch(db, user1.id, user2.id)


class TestEditDeleteAfterSettle:
    """Invariant #10 — editing or deleting an already-settled shared expense
    is allowed and silently re-derives the balance (no blocking)."""

    def test_edit_settled_expense_redrives(
        self, db, seeded_users, seeded_categories, mock_frankfurter
    ):
        user1, user2 = seeded_users
        cat1 = seeded_categories[0].id
        cat2 = _partner_category_id(db, user2)
        occurred_on = date(2026, 6, 15)

        # user1 pays SGD 100.00 split equally -> user2 (partner) owes user1 5000
        header, _, _ = create_shared_expense(
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
        record_settlement(db, user2.id, user1.id, "50.00", "SGD", occurred_on)
        assert "SGD" not in compute_balance(db, user1.id, user2.id)

        # Raise the total to SGD 200.00 -> partner's new share is 100.00 (10000)
        update_shared_expense(
            db, user1.id, header.id, amount_str="200.00", split_input={}
        )

        bal = compute_balance(db, user1.id, user2.id)
        assert bal["SGD"] == 5000  # 10000 new share - 5000 already-settled

    def test_delete_settled_expense_redrives(
        self, db, seeded_users, seeded_categories, mock_frankfurter
    ):
        user1, user2 = seeded_users
        cat1 = seeded_categories[0].id
        cat2 = _partner_category_id(db, user2)
        occurred_on = date(2026, 6, 15)

        header, _, _ = create_shared_expense(
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
        record_settlement(db, user2.id, user1.id, "50.00", "SGD", occurred_on)
        assert "SGD" not in compute_balance(db, user1.id, user2.id)

        delete_shared_expense(db, user1.id, header.id)

        # The debt is gone but the recorded settlement remains until voided —
        # only the settlement's contribution is left in the balance.
        bal = compute_balance(db, user1.id, user2.id)
        assert bal["SGD"] == -5000
