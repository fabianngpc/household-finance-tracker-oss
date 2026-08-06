"""
Recurring-expenses service (date math + idempotent catch-up).

Design rules:
- due_dates() uses dateutil.relativedelta(day=N) for monthly/monthly_nth math
  — it CLAMPS to the real last day of the month (31st -> 30/28/29, Feb-29 ->
  Feb-28 in non-leap years). Never hand-roll date(y, m, N) here; it raises
  ValueError on invalid days.
- generate_due() is the whole idempotency story: a RecurringOccurrence
  marker (rule_id, period_key) is db.add()-ed into the SAME session that the
  create_* helper commits, so the marker and the generated expense land in
  ONE transaction. A concurrent/second run loses the UNIQUE(rule_id,
  period_key) race with an IntegrityError and rolls back cleanly — no
  duplicate is ever possible, regardless of application-level bugs.
- Every generated expense is dated to its REAL due date (occurred_on=due),
  never "today" — a backfilled March rent stays in March's reports.
- Editing a rule (update_rule) only ever mutates recurring_rules; it never
  touches previously generated Expense rows (no retro-recompute).
- pause_rule/resume_rule use the generate_from watermark to distinguish
  "missed while asleep/off" (never touches generate_from, so downtime always
  backfills) from "intentionally paused" (resume_rule snaps generate_from
  forward to the resume date, so the paused window is skipped forever).
"""

import json
from datetime import date, datetime, timedelta, timezone

from dateutil.relativedelta import relativedelta
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.expense import Expense
from app.models.notification import OutboundNotification
from app.models.recurring import RecurringOccurrence, RecurringRule
from app.models.user import User
from app.services.expenses import create_expense_from_data
from app.services.money import format_from_minor_units
from app.services.shared_expenses import create_shared_expense


def due_dates(rule: RecurringRule, start: date, until: date) -> list[date]:
    """
    Return every due date in [start, until] (inclusive) for `rule`, truncated
    by `rule.end_date` if set.

    - weekly: anchor_date + timedelta(weeks=k).
    - monthly / monthly_nth: anchor_date + relativedelta(months=k, day=N),
      which CLAMPS day=N to the real last day of the target month (handles
      31st-in-a-30-day-month and Feb-29 safely — no ValueError).
    """
    out: list[date] = []
    if rule.frequency == "weekly":
        k = 0
        d = rule.anchor_date
        while d <= until:
            if rule.end_date and d > rule.end_date:
                break
            if d >= start:
                out.append(d)
            k += 1
            d = rule.anchor_date + timedelta(weeks=k)
    else:  # monthly / monthly_nth
        k = 0
        target_day = rule.day_of_month or rule.anchor_date.day
        while True:
            d = rule.anchor_date + relativedelta(months=k, day=target_day)
            if d > until:
                break
            if rule.end_date and d > rule.end_date:
                break
            if d >= start:
                out.append(d)
            k += 1
    return out


def next_run_date(rule: RecurringRule, today: date | None = None) -> date | None:
    """First due date strictly AFTER `today` (None if paused, or if
    `end_date` has already passed)."""
    if today is None:
        today = date.today()
    if rule.paused:
        return None
    if rule.end_date and today >= rule.end_date:
        return None

    start = today + timedelta(days=1)
    until = rule.end_date if rule.end_date else start + timedelta(days=370)
    dates = due_dates(rule, start=start, until=until)
    return dates[0] if dates else None


def _currency_prefix(currency: str) -> str:
    return "S$" if currency == "SGD" else f"{currency} "


def _format_display_amount(minor: int, currency: str) -> str:
    """Human-facing amount with thousands separators, matching the UI-SPEC
    Telegram copy examples ("S$19.98", "S$2,000.00")."""
    raw = format_from_minor_units(minor, currency)
    prefix = _currency_prefix(currency)
    sign = ""
    if raw.startswith("-"):
        sign = "-"
        raw = raw[1:]
    if "." in raw:
        int_part, dec_part = raw.split(".", 1)
        int_part = f"{int(int_part):,}"
        return f"{prefix}{sign}{int_part}.{dec_part}"
    return f"{prefix}{sign}{int(raw):,}"


def _format_period_label(period_key: str) -> str:
    try:
        return date.fromisoformat(period_key).strftime("%b %-d")
    except ValueError:
        return period_key


def _enqueue_notification(
    db: Session, rule: RecurringRule, created: list[RecurringOccurrence]
) -> None:
    """Enqueue ONE OutboundNotification for this generation run: the
    solo/shared copy for a single period, or a collapsed "caught up" summary
    for a multi-period backfill. Silently skipped if the owner has never
    linked a Telegram account (no telegram_id)."""
    owner = db.get(User, rule.owner_user_id)
    if owner is None or owner.telegram_id is None:
        return

    name = rule.merchant or "Recurring"

    if len(created) > 1:
        first_label = _format_period_label(created[0].period_key)
        last_label = _format_period_label(created[-1].period_key)
        body = (
            f"Recurring caught up: {name} — {len(created)} runs logged "
            f"({first_label}–{last_label})."
        )
    else:
        amt = _format_display_amount(rule.amount_minor, rule.currency)
        if rule.is_shared:
            payer_expense = (
                db.query(Expense)
                .filter(
                    Expense.shared_expense_id == created[0].shared_expense_id,
                    Expense.user_id == rule.owner_user_id,
                )
                .first()
            )
            half_minor = (
                payer_expense.original_amount_minor
                if payer_expense is not None
                else rule.amount_minor
            )
            half = _format_display_amount(half_minor, rule.currency)
            body = f"Recurring logged: {name} {amt} — your half {half}."
        else:
            body = f"Recurring logged: {name} {amt}."

    db.add(
        OutboundNotification(
            telegram_chat_id=owner.telegram_id,
            body=body,
            status="pending",
        )
    )
    db.commit()


def generate_due(
    db: Session, rule: RecurringRule, today: date | None = None
) -> list[RecurringOccurrence]:
    """
    Backfill every due period in [rule.generate_from, today] that has not
    already been generated, creating one Expense (solo) or one SharedExpense
    fan-out (shared) per period, each dated to its real due date.

    Idempotent: a period already claimed by a RecurringOccurrence marker
    hits IntegrityError on UNIQUE(rule_id, period_key) and is skipped — a
    second call with the same `today` creates zero new rows.

    Returns the list of newly created RecurringOccurrence markers (empty if
    the rule is paused or every due period was already generated).
    """
    if today is None:
        today = date.today()
    if rule.paused:
        return []

    created: list[RecurringOccurrence] = []

    for due in due_dates(rule, start=rule.generate_from, until=today):
        marker = RecurringOccurrence(rule_id=rule.id, period_key=due.isoformat())
        db.add(marker)
        try:
            if rule.is_shared:
                partner = (
                    db.query(User).filter(User.id != rule.owner_user_id).first()
                )
                header, _payer_row, _partner_row = create_shared_expense(
                    db,
                    payer_id=rule.owner_user_id,
                    partner_id=partner.id,
                    amount_str=format_from_minor_units(rule.amount_minor, rule.currency),
                    currency=rule.currency,
                    occurred_on=due,
                    split_method=rule.split_method,
                    payer_category_id=rule.category_id,
                    partner_category_id=rule.partner_category_id,
                    split_input=json.loads(rule.split_input_json or "{}"),
                    merchant=rule.merchant,
                )
                marker.shared_expense_id = header.id
            else:
                exp = create_expense_from_data(
                    db,
                    user_id=rule.owner_user_id,
                    amount_str=format_from_minor_units(rule.amount_minor, rule.currency),
                    currency=rule.currency,
                    category_id=rule.category_id,
                    expense_date=due,
                    merchant=rule.merchant,
                    source="recurring",
                )
                marker.expense_id = exp.id
            db.commit()  # link-id persist (marker already committed with the expense)
        except IntegrityError:
            db.rollback()  # (rule, period_key) already generated -> skip, no dup
            continue
        created.append(marker)

    if created:
        _enqueue_notification(db, rule, created)

    return created


def create_rule(db: Session, **fields) -> RecurringRule:
    """Create a rule; generate_from defaults to anchor_date (the catch-up
    watermark starts at the rule's own first due date)."""
    if "generate_from" not in fields or fields["generate_from"] is None:
        fields["generate_from"] = fields["anchor_date"]
    rule = RecurringRule(**fields)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def update_rule(db: Session, rule_id: int, **fields) -> RecurringRule:
    """Mutate a rule in place. Future-only: never touches previously
    generated Expense rows."""
    rule = db.get(RecurringRule, rule_id)
    if rule is None:
        raise ValueError(f"Recurring rule {rule_id} not found")
    for key, value in fields.items():
        if hasattr(rule, key):
            setattr(rule, key, value)
    rule.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(rule)
    return rule


def pause_rule(db: Session, rule_id: int) -> RecurringRule:
    rule = db.get(RecurringRule, rule_id)
    if rule is None:
        raise ValueError(f"Recurring rule {rule_id} not found")
    rule.paused = True
    db.commit()
    db.refresh(rule)
    return rule


def resume_rule(db: Session, rule_id: int, today: date | None = None) -> RecurringRule:
    """Resume a paused rule and advance generate_from to `today` so the
    paused window is never backfilled (only downtime is)."""
    if today is None:
        today = date.today()
    rule = db.get(RecurringRule, rule_id)
    if rule is None:
        raise ValueError(f"Recurring rule {rule_id} not found")
    rule.paused = False
    rule.generate_from = today
    db.commit()
    db.refresh(rule)
    return rule


def delete_rule(db: Session, rule_id: int) -> None:
    rule = db.get(RecurringRule, rule_id)
    if rule is None:
        raise ValueError(f"Recurring rule {rule_id} not found")
    db.delete(rule)
    db.commit()


def list_rules(db: Session, owner_user_id: int) -> list[RecurringRule]:
    return (
        db.query(RecurringRule)
        .filter(RecurringRule.owner_user_id == owner_user_id)
        .order_by(RecurringRule.id)
        .all()
    )
