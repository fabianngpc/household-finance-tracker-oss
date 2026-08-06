"""
Recurring-rules API — protected by get_current_user. Operates on the CURRENT
user's own rules only (owner_user_id scoping).

Routes registered under /api (main.py mounts this router with prefix="/api").

GET    /recurring               -> list[RecurringRuleOut] (owner's rules, with computed next_run)
POST   /recurring                -> 201 RecurringRuleOut
PATCH  /recurring/{id}           -> RecurringRuleOut (future-only edit)
POST   /recurring/{id}/pause     -> RecurringRuleOut
POST   /recurring/{id}/resume    -> RecurringRuleOut
DELETE /recurring/{id}           -> {"ok": True}
"""

import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models.recurring import RecurringRule
from app.models.user import User
from app.schemas.recurring import RecurringRuleCreate, RecurringRuleOut, RecurringRuleUpdate
from app.services.money import parse_to_minor_units
from app.services.recurring import (
    create_rule,
    delete_rule,
    list_rules,
    next_run_date,
    pause_rule,
    resume_rule,
    update_rule,
)

router = APIRouter()


def _build_split_input(
    split_method: str | None,
    currency: str,
    payer_pct: int | None,
    partner_pct: int | None,
    payer_amount: str | None,
    partner_amount: str | None,
) -> dict:
    """Build the split_input dict for the service layer from wire fields.

    Mirrors app/routers/shared_expenses.py::_build_split_input so shared
    recurring rules and one-off shared expenses never diverge on split
    validation.
    """
    if split_method == "percent":
        if payer_pct is None or partner_pct is None:
            raise HTTPException(
                status_code=400,
                detail="payer_pct and partner_pct are required for percent split",
            )
        return {"payer_pct": payer_pct, "partner_pct": partner_pct}
    elif split_method == "exact":
        if payer_amount is None or partner_amount is None:
            raise HTTPException(
                status_code=400,
                detail="payer_amount and partner_amount are required for exact split",
            )
        try:
            return {
                "payer_minor": parse_to_minor_units(payer_amount, currency),
                "partner_minor": parse_to_minor_units(partner_amount, currency),
            }
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    else:
        return {}


def _get_owned_rule(db: Session, user: User, rule_id: int) -> RecurringRule:
    rule = db.get(RecurringRule, rule_id)
    if rule is None or rule.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Recurring rule not found")
    return rule


def _to_rule_out(rule: RecurringRule, today: date | None = None) -> RecurringRuleOut:
    return RecurringRuleOut(
        id=rule.id,
        name=rule.merchant,
        amount_minor=rule.amount_minor,
        currency=rule.currency,
        category_id=rule.category_id,
        frequency=rule.frequency,
        day_of_month=rule.day_of_month,
        weekday=rule.weekday,
        starts_on=rule.anchor_date,
        end_date=rule.end_date,
        paused=rule.paused,
        is_shared=rule.is_shared,
        split_method=rule.split_method,
        partner_category_id=rule.partner_category_id,
        next_run=next_run_date(rule, today=today),
    )


@router.get("/recurring", response_model=list[RecurringRuleOut])
def list_recurring_rules(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List the current user's recurring rules, each with a computed next_run."""
    today = date.today()
    return [_to_rule_out(rule, today=today) for rule in list_rules(db, user.id)]


@router.post("/recurring", response_model=RecurringRuleOut, status_code=201)
def create_recurring_rule(
    body: RecurringRuleCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a recurring rule owned by the current user.

    Returns 400 for an invalid amount/currency or an invalid split
    configuration (missing percent/exact fields, percentages not summing to
    100, or exact amounts not summing to the total).
    """
    split_input = _build_split_input(
        body.split_method,
        body.currency,
        body.payer_pct,
        body.partner_pct,
        body.payer_amount,
        body.partner_amount,
    )

    try:
        amount_minor = parse_to_minor_units(body.amount, body.currency)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        rule = create_rule(
            db,
            owner_user_id=user.id,
            amount_minor=amount_minor,
            currency=body.currency,
            category_id=body.category_id,
            merchant=body.name,
            frequency=body.frequency,
            day_of_month=body.day_of_month,
            weekday=body.weekday,
            anchor_date=body.starts_on,
            end_date=body.end_date,
            is_shared=body.is_shared,
            split_method=body.split_method,
            split_input_json=json.dumps(split_input) if split_input else None,
            partner_category_id=body.partner_category_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return _to_rule_out(rule)


@router.patch("/recurring/{id}", response_model=RecurringRuleOut)
def update_recurring_rule(
    id: int,
    body: RecurringRuleUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Edit a rule in place — future generations only; already-generated
    Expense rows are never touched. Omitted fields are left unchanged."""
    _get_owned_rule(db, user, id)

    fields: dict = {}
    if body.name is not None:
        fields["merchant"] = body.name
    if body.currency is not None:
        fields["currency"] = body.currency
    if body.category_id is not None:
        fields["category_id"] = body.category_id
    if body.frequency is not None:
        fields["frequency"] = body.frequency
    if body.day_of_month is not None:
        fields["day_of_month"] = body.day_of_month
    if body.weekday is not None:
        fields["weekday"] = body.weekday
    if body.starts_on is not None:
        fields["anchor_date"] = body.starts_on
    if body.end_date is not None:
        fields["end_date"] = body.end_date
    if body.is_shared is not None:
        fields["is_shared"] = body.is_shared
    if body.split_method is not None:
        fields["split_method"] = body.split_method
    if body.partner_category_id is not None:
        fields["partner_category_id"] = body.partner_category_id

    effective_currency = body.currency if body.currency is not None else db.get(RecurringRule, id).currency
    if body.amount is not None:
        try:
            fields["amount_minor"] = parse_to_minor_units(body.amount, effective_currency)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    if body.split_method is not None or any(
        v is not None
        for v in (body.payer_pct, body.partner_pct, body.payer_amount, body.partner_amount)
    ):
        split_input = _build_split_input(
            body.split_method,
            effective_currency,
            body.payer_pct,
            body.partner_pct,
            body.payer_amount,
            body.partner_amount,
        )
        fields["split_input_json"] = json.dumps(split_input) if split_input else None

    try:
        rule = update_rule(db, id, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return _to_rule_out(rule)


@router.post("/recurring/{id}/pause", response_model=RecurringRuleOut)
def pause_recurring_rule(
    id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_owned_rule(db, user, id)
    rule = pause_rule(db, id)
    return _to_rule_out(rule)


@router.post("/recurring/{id}/resume", response_model=RecurringRuleOut)
def resume_recurring_rule(
    id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Resume a paused rule; generate_from advances to today so the paused
    window is never backfilled."""
    _get_owned_rule(db, user, id)
    rule = resume_rule(db, id)
    return _to_rule_out(rule)


@router.delete("/recurring/{id}")
def delete_recurring_rule(
    id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_owned_rule(db, user, id)
    delete_rule(db, id)
    return {"ok": True}
