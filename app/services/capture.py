"""
Capture state-machine service: the Telegram-agnostic orchestration layer.

This is the canonical capture write-path:
  enqueue -> claim -> process -> (confirm? -> apply_confirm_input) -> save
  -> save_capture_expense -> create_expense_from_data(source="telegram")

Design rules:
- Never compute money/FX here — delegate entirely to create_expense_from_data.
- parse_to_minor_units is used ONLY for confirm-flow validation.
- Idempotent on update_id (UNIQUE constraint + IntegrityError catch).
- Atomic job claim via BEGIN IMMEDIATE on the raw DBAPI connection.
"""

from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.capture import Capture
from app.models.expense import Expense
from app.models.job import Job
from app.services.categories import resolve_category_for_hint, resolve_other_category_id
from app.services.expenses import create_expense_from_data, update_expense
from app.services.money import CURRENCY_DECIMALS, parse_to_minor_units
from bot.extractor import ExtractionResult


# ---------------------------------------------------------------------------
# Enqueue (idempotent)
# ---------------------------------------------------------------------------

def enqueue_capture(
    db: Session,
    *,
    update_id: int,
    telegram_user_id: int,
    telegram_chat_id: int,
    user_id: int,
    raw_text: str,
    image_path: str | None = None,
) -> Capture | None:
    """
    Idempotently enqueue a Telegram message for processing.

    Creates a Capture(status='queued') + Job(status='pending').
    Returns the Capture on success, or None if update_id already exists
    (duplicate update_id is a silent no-op — idempotency key).
    """
    try:
        capture = Capture(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            user_id=user_id,
            raw_message=raw_text,
            status="queued",
            image_path=image_path,
        )
        db.add(capture)
        db.flush()  # get capture.id before commit

        job = Job(capture_id=capture.id, status="pending")
        db.add(job)
        db.commit()
        db.refresh(capture)
        return capture
    except IntegrityError:
        db.rollback()
        return None


# ---------------------------------------------------------------------------
# Atomic job claim (BEGIN IMMEDIATE)
# ---------------------------------------------------------------------------

def claim_next_job(engine) -> dict | None:
    """
    Atomically claim exactly one pending job using BEGIN IMMEDIATE.

    Uses the raw DBAPI connection to issue an explicit immediate transaction
    (SQLAlchemy's Connection would otherwise emit its own BEGIN, losing
    the write-lock guarantee).

    Returns {"job_id": int, "capture_id": int} or None if no pending jobs.
    """
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute("BEGIN IMMEDIATE")
        cur.execute(
            "SELECT id, capture_id FROM jobs "
            "WHERE status='pending' ORDER BY created_at ASC, id ASC LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            cur.execute("COMMIT")
            return None
        cur.execute(
            "UPDATE jobs SET status='processing', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (row[0],),
        )
        cur.execute("COMMIT")
        return {"job_id": row[0], "capture_id": row[1]}
    finally:
        raw.close()


# ---------------------------------------------------------------------------
# Complete a job
# ---------------------------------------------------------------------------

def complete_job(db: Session, job_id: int, status: str, error: str | None = None) -> None:
    """Set a job's final status (e.g. 'done' or 'failed')."""
    job = db.query(Job).filter_by(id=job_id).first()
    if job is None:
        return
    job.status = status
    if error is not None:
        job.error = error
    db.commit()


# ---------------------------------------------------------------------------
# Per-field confidence thresholds
# ---------------------------------------------------------------------------

# Amount must meet this threshold to auto-save without asking the user.
CONF_AMOUNT_THRESHOLD = 0.7

# Category must meet this threshold to use the AI hint; otherwise fall back to 'Other'.
CONF_CATEGORY_THRESHOLD = 0.5

# Used when a capture has no currency, or one the app doesn't support.
DEFAULT_CURRENCY = "SGD"


def _effective_confidence_amount(result: ExtractionResult) -> float:
    """Return the amount confidence for a result, with backward-compat fallback.

    New extractors set confidence_amount explicitly.
    Legacy StubExtractor-shaped results leave confidence_amount=None and rely on
    the top-level `confidence` field instead (1.0 = amount found, 0.0 = not found).
    """
    if result.confidence_amount is not None:
        return result.confidence_amount
    return result.confidence


# ---------------------------------------------------------------------------
# Confidence gate
# ---------------------------------------------------------------------------

def process_capture(db: Session, capture: Capture, result: ExtractionResult) -> Capture:
    """
    Apply an ExtractionResult to a Capture and advance state.

    Gating is driven by per-field confidence:

    Amount-confident (conf_amount ≥ CONF_AMOUNT_THRESHOLD):
        Resolve category (hint if confident, else 'Other'), set capture.category_id,
        store all fields, then save immediately → capture.status='done'.

    Low-amount-confidence (conf_amount < CONF_AMOUNT_THRESHOLD):
        Park in pending_confirm/confirm_step='amount' (existing single-step flow).
        Category is still resolved silently — stored on capture for later save.
        No 'category' confirm step is ever added.

    Backward compat: results with confidence_amount=None fall back to `confidence`
    (StubExtractor: 1.0 if amount found, 0.0 if not).
    """
    conf_amount = _effective_confidence_amount(result)

    # Resolve category silently — never a blocking confirm step.
    # Confident hint → matched category; uncertain or unknown → 'Other'.
    if result.confidence_category >= CONF_CATEGORY_THRESHOLD:
        category_id = resolve_category_for_hint(db, capture.user_id, result.category_hint)
    else:
        category_id = resolve_other_category_id(db, capture.user_id)
    capture.category_id = category_id

    if conf_amount >= CONF_AMOUNT_THRESHOLD:
        # High confidence — store extraction fields then save immediately
        capture.amount_str = result.amount_str
        capture.currency = result.currency
        capture.merchant = result.merchant
        capture.expense_date = result.expense_date.isoformat()
        db.flush()
        save_capture_expense(db, capture)
    else:
        # Low confidence — park for single-step amount confirm flow
        capture.status = "pending_confirm"
        capture.confirm_step = "amount"
        capture.currency = result.currency
        capture.expense_date = result.expense_date.isoformat()
        capture.merchant = result.merchant
        db.commit()

    return capture


# ---------------------------------------------------------------------------
# Confirm-step handler
# ---------------------------------------------------------------------------

def apply_confirm_input(db: Session, capture: Capture, text: str) -> Capture:
    """
    Handle user input for the current confirm_step.

    confirm_step='amount':
        Validates text via parse_to_minor_units(text, capture.currency or 'SGD').
        On ValueError: set capture.error=str(e), commit, return unchanged.

        First save (capture.expense_id is None):
            set capture.amount_str=text, then save_capture_expense — INSERTs a
            new expense row (unchanged initial-confirm behavior).

        Re-edit (capture.expense_id points at an existing, non-shared expense):
            UPDATE that expense's amount in place via the canonical
            update_expense write-path, preserving the expense id — never insert
            a duplicate (money double-count).  A shared linked expense is left
            untouched (mirrors the /undo and phrase-handler guards).
    """
    if capture.confirm_step == "amount":
        # Self-heal an unsupported stored currency before parsing. A KeyError
        # here comes from the currency, not the user's input, so without this
        # the capture is unclearable: every amount the user types fails the same
        # way and the bot re-prompts forever. Repairing it in place means the
        # next reply — or even this one, on retry — can succeed.
        currency = capture.currency or DEFAULT_CURRENCY
        if currency not in CURRENCY_DECIMALS:
            currency = DEFAULT_CURRENCY
            capture.currency = currency

        try:
            parse_to_minor_units(text, currency)
        except (ValueError, KeyError) as exc:
            capture.error = str(exc)
            db.commit()
            return capture

        # Re-edit path: an expense already exists for this capture.
        existing = (
            db.get(Expense, capture.expense_id)
            if capture.expense_id is not None
            else None
        )
        if existing is not None:
            # Never mutate a shared-expense child from the confirm flow.
            if existing.shared_expense_id is not None:
                return capture

            update_expense(
                db,
                user_id=capture.user_id,
                expense_id=existing.id,
                amount_str=text,
            )
            capture.amount_str = text
            capture.status = "done"
            capture.confirm_step = "post_save"
            db.commit()
            return capture

        # First-save path: no expense yet — create one (unchanged).
        capture.amount_str = text
        db.flush()
        save_capture_expense(db, capture)

    return capture


# ---------------------------------------------------------------------------
# Write-path save (always via create_expense_from_data)
# ---------------------------------------------------------------------------

def save_capture_expense(db: Session, capture: Capture) -> Expense:
    """
    Persist the capture as an expense via the canonical write-path.

    Always calls create_expense_from_data(..., source="telegram").
    Never computes money or FX itself — that logic lives in the write-path.

    Uses the resolved category_id already stored on capture (set by process_capture).
    Falls back to 'Other' when capture.category_id is None (e.g. direct call from
    apply_confirm_input without going through process_capture).

    Uses date.fromisoformat(capture.expense_date) for the FX date,
    so timezone drift cannot corrupt the rate.
    """
    capture.status = "saving"

    currency = capture.currency or "SGD"
    category_id = (
        capture.category_id
        if capture.category_id is not None
        else resolve_other_category_id(db, capture.user_id)
    )
    expense_date = date.fromisoformat(capture.expense_date)

    expense = create_expense_from_data(
        db,
        user_id=capture.user_id,
        amount_str=capture.amount_str,
        currency=currency,
        category_id=category_id,
        expense_date=expense_date,
        merchant=capture.merchant,
        source="telegram",
    )

    capture.expense_id = expense.id
    capture.category_id = category_id
    capture.status = "done"
    capture.confirm_step = "post_save"
    db.commit()

    return expense


# resolve_other_category_id and resolve_category_for_hint live in
# app.services.categories and are imported above.
# Re-export resolve_other_category_id so existing callers that do
# `from app.services.capture import resolve_other_category_id` still work.
__all__ = [
    "CONF_AMOUNT_THRESHOLD",
    "CONF_CATEGORY_THRESHOLD",
    "_effective_confidence_amount",
    "enqueue_capture",
    "claim_next_job",
    "complete_job",
    "process_capture",
    "apply_confirm_input",
    "save_capture_expense",
    "resolve_other_category_id",
]
