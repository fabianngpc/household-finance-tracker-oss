"""
Shared-expense write-path service: fans out one shared expense into a header
row (shared_expenses) plus two linked per-user expense rows (payer share +
partner share).

Design rules:
- FX is fetched ONCE (get_rate_for_date) and reused for both children — the
  historical rate/date must match across the header and both share rows.
- Split shares are computed via _compute_shares() (allocate_shares() for
  equal, explicit validation for percent/exact) — never silently reconciled.
  Both create_shared_expense and update_shared_expense call this single
  helper so the split logic never diverges between the two paths.
- Header + both children are persisted in a single db.commit() so the fan-out
  (create) and the cascade (update/delete) are atomic: a failure partway
  through never leaves an orphaned header or a lone child row.
- update_shared_expense updates the two child rows IN PLACE (never deletes
  and recreates them) so ids/created_at are preserved.
"""

from decimal import Decimal

from app.models.expense import Expense
from app.models.shared_expense import SharedExpense
from app.services.fx import compute_base_amount_minor, get_rate_for_date
from app.services.money import CURRENCY_DECIMALS, allocate_shares, parse_to_minor_units


def _compute_shares(
    total_minor: int, split_method: str, split_input: dict
) -> tuple[int, int]:
    """
    Resolve (payer_share, partner_share) for a given total and split method.

    split_input shape depends on split_method:
      - "equal":   {} (ignored — 1:1 weights)
      - "percent": {"payer_pct": int, "partner_pct": int} — must sum to 100
      - "exact":   {"payer_minor": int, "partner_minor": int} — must sum to total

    Raises:
        ValueError: unknown split_method, percentages not summing to 100,
            or exact amounts not summing to the total.
    """
    if split_method == "equal":
        payer_share, partner_share = allocate_shares(
            total_minor, [Decimal(1), Decimal(1)]
        )
    elif split_method == "percent":
        p = split_input["payer_pct"]
        q = split_input["partner_pct"]
        if p + q != 100:
            raise ValueError("Percentages must sum to 100")
        payer_share, partner_share = allocate_shares(
            total_minor, [Decimal(p), Decimal(q)]
        )
    elif split_method == "exact":
        payer_share = split_input["payer_minor"]
        partner_share = split_input["partner_minor"]
        if payer_share + partner_share != total_minor:
            raise ValueError("Exact amounts don't sum to the total")
    else:
        raise ValueError(f"Unknown split_method: {split_method!r}")

    return payer_share, partner_share


def create_shared_expense(
    db,
    payer_id,
    partner_id,
    amount_str,
    currency,
    occurred_on,
    split_method,
    payer_category_id,
    partner_category_id,
    split_input,
    merchant=None,
) -> tuple[SharedExpense, Expense, Expense]:
    """
    Create a shared expense: one SharedExpense header + two linked Expense rows.

    split_input shape depends on split_method:
      - "equal":   {} (ignored — 1:1 weights)
      - "percent": {"payer_pct": int, "partner_pct": int} — must sum to 100
      - "exact":   {"payer_minor": int, "partner_minor": int} — must sum to total

    Raises:
        ValueError: unsupported currency, unknown split_method, percentages
            not summing to 100, or exact amounts not summing to the total.
    """
    if currency not in CURRENCY_DECIMALS:
        raise ValueError(f"Unsupported currency: {currency!r}")

    total_minor = parse_to_minor_units(amount_str, currency)
    rate, rate_date = get_rate_for_date(occurred_on, currency, db)

    payer_share, partner_share = _compute_shares(total_minor, split_method, split_input)

    header = SharedExpense(
        payer_user_id=payer_id,
        total_amount_minor=total_minor,
        original_currency=currency,
        split_method=split_method,
        occurred_on=occurred_on,
        fx_rate=rate,
        fx_rate_date=rate_date,
    )
    db.add(header)
    db.flush()  # assigns header.id without committing

    payer_row = Expense(
        user_id=payer_id,
        original_amount_minor=payer_share,
        original_currency=currency,
        amount_base_minor=compute_base_amount_minor(payer_share, currency, rate),
        fx_rate=rate,
        fx_rate_date=rate_date,
        category_id=payer_category_id,
        occurred_on=occurred_on,
        merchant=merchant,
        source="web",
        shared_expense_id=header.id,
    )
    partner_row = Expense(
        user_id=partner_id,
        original_amount_minor=partner_share,
        original_currency=currency,
        amount_base_minor=compute_base_amount_minor(partner_share, currency, rate),
        fx_rate=rate,
        fx_rate_date=rate_date,
        category_id=partner_category_id,
        occurred_on=occurred_on,
        merchant=merchant,
        source="web",
        shared_expense_id=header.id,
    )
    db.add(payer_row)
    db.add(partner_row)
    db.commit()

    db.refresh(header)
    db.refresh(payer_row)
    db.refresh(partner_row)

    from app.services.budget_alerts import check_budget_alerts

    # Each child's own share counts toward that owner's TOTAL budget.
    check_budget_alerts(db, payer_id, occurred_on)
    check_budget_alerts(db, partner_id, occurred_on)

    return header, payer_row, partner_row


def delete_shared_expense(db, requester_id, shared_expense_id) -> None:
    """
    Delete a shared expense: removes the header AND both linked child Expense
    rows atomically (single db.commit()).

    Raises:
        HTTPException(404): shared expense doesn't exist, or requester_id is
            neither the payer nor the partner (either of the two children's
            owners).
    """
    from fastapi import HTTPException

    header = db.get(SharedExpense, shared_expense_id)
    if header is None:
        raise HTTPException(status_code=404, detail="Shared expense not found")

    children = (
        db.query(Expense).filter(Expense.shared_expense_id == shared_expense_id).all()
    )

    allowed_ids = {header.payer_user_id, *[c.user_id for c in children]}
    if requester_id not in allowed_ids:
        raise HTTPException(status_code=404, detail="Shared expense not found")

    for child in children:
        db.delete(child)
    db.delete(header)
    db.commit()


def update_shared_expense(
    db,
    requester_id,
    shared_expense_id,
    amount_str=None,
    currency=None,
    occurred_on=None,
    split_method=None,
    split_input=None,
    payer_category_id=None,
    partner_category_id=None,
    merchant=None,
) -> tuple[SharedExpense, Expense, Expense]:
    """
    Edit a shared expense in place: re-derives both linked child Expense rows
    and the header in a single db.commit(). Never deletes/recreates children
    (ids/created_at preserved).

    Only the payer may call this (money edits must flow through here so both
    children + header stay in sync — the partner recategorizes their own row
    via the generic expense PATCH instead).

    Raises:
        HTTPException(404): shared expense not found.
        HTTPException(403): requester is not the payer.
        ValueError: unsupported currency, unknown split_method, percentages
            not summing to 100, or exact amounts not summing to the total.
    """
    from fastapi import HTTPException

    header = db.get(SharedExpense, shared_expense_id)
    if header is None:
        raise HTTPException(status_code=404, detail="Shared expense not found")

    if requester_id != header.payer_user_id:
        raise HTTPException(
            status_code=403, detail="Only the payer can edit a shared expense"
        )

    children = (
        db.query(Expense).filter(Expense.shared_expense_id == shared_expense_id).all()
    )
    payer_row = next(c for c in children if c.user_id == header.payer_user_id)
    partner_row = next(c for c in children if c.user_id != header.payer_user_id)

    # Resolve effective values (fall back to current header values)
    eff_currency = currency if currency is not None else header.original_currency
    eff_occurred_on = occurred_on if occurred_on is not None else header.occurred_on
    eff_method = split_method if split_method is not None else header.split_method

    if eff_currency not in CURRENCY_DECIMALS:
        raise ValueError(f"Unsupported currency: {eff_currency!r}")

    if amount_str is not None:
        total_minor = parse_to_minor_units(amount_str, eff_currency)
    else:
        total_minor = header.total_amount_minor

    money_changed = (
        amount_str is not None or currency is not None or occurred_on is not None
    )
    if money_changed:
        rate, rate_date = get_rate_for_date(eff_occurred_on, eff_currency, db)
    else:
        rate, rate_date = header.fx_rate, header.fx_rate_date

    payer_share, partner_share = _compute_shares(
        total_minor, eff_method, split_input or {}
    )

    payer_row.original_amount_minor = payer_share
    payer_row.original_currency = eff_currency
    payer_row.amount_base_minor = compute_base_amount_minor(
        payer_share, eff_currency, rate
    )
    payer_row.fx_rate = rate
    payer_row.fx_rate_date = rate_date
    payer_row.occurred_on = eff_occurred_on

    partner_row.original_amount_minor = partner_share
    partner_row.original_currency = eff_currency
    partner_row.amount_base_minor = compute_base_amount_minor(
        partner_share, eff_currency, rate
    )
    partner_row.fx_rate = rate
    partner_row.fx_rate_date = rate_date
    partner_row.occurred_on = eff_occurred_on

    if payer_category_id is not None:
        payer_row.category_id = payer_category_id
    if partner_category_id is not None:
        partner_row.category_id = partner_category_id
    if merchant is not None:
        payer_row.merchant = merchant
        partner_row.merchant = merchant

    header.total_amount_minor = total_minor
    header.original_currency = eff_currency
    header.split_method = eff_method
    header.occurred_on = eff_occurred_on
    header.fx_rate = rate
    header.fx_rate_date = rate_date

    db.commit()

    db.refresh(header)
    db.refresh(payer_row)
    db.refresh(partner_row)

    from app.services.budget_alerts import check_budget_alerts

    check_budget_alerts(db, header.payer_user_id, header.occurred_on)
    check_budget_alerts(db, partner_row.user_id, header.occurred_on)

    return header, payer_row, partner_row
