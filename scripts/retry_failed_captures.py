"""Retry Telegram captures that failed FX conversion and were never saved.

Background: captures in a supported currency that couldn't resolve an FX rate
(e.g. the IDR/THB gap fixed in fx.py) were marked status='failed' with no
expense ever created — the user saw only "Got it, processing..." and the spend
never reached the ledger. This script re-drives the save for those rows through
the canonical write-path (save_capture_expense), which now succeeds because the
rate lookup is fixed.

Only rows that are safe to reconstruct are retried:
  - status = 'failed'
  - expense_id IS NULL          (never saved — no risk of a double-count)
  - amount_str, currency, expense_date all populated (set before the FX failure)
  - currency is one the app supports (CURRENCY_DECIMALS)

Each row is retried in isolation: a row that fails again (e.g. network FX
lookup down) is rolled back, left as 'failed', and reported — it never aborts
the run. On success the capture becomes 'done' and, unless --no-notify is
given, a Telegram message is queued (via outbound_notifications, delivered by
the running worker) so the user learns the spend was recovered.

Run it where the LIVE database lives (set FINANCE_DB_PATH, same as the other
scripts). Take a backup first: `uv run python -m scripts.backup`.

Usage:
    uv run python -m scripts.retry_failed_captures --dry-run   # preview only
    uv run python -m scripts.retry_failed_captures             # apply + notify
    uv run python -m scripts.retry_failed_captures --no-notify # apply, silent
"""
import argparse

from app.database import SessionLocal
from app.models.capture import Capture
from app.models.category import Category
from app.models.notification import OutboundNotification
from app.services.capture import save_capture_expense
from app.services.money import CURRENCY_DECIMALS


def find_retryable(db):
    """Return the failed, never-saved captures that are safe to re-drive."""
    return (
        db.query(Capture)
        .filter(
            Capture.status == "failed",
            Capture.expense_id.is_(None),
            Capture.amount_str.isnot(None),
            Capture.currency.isnot(None),
            Capture.currency.in_(list(CURRENCY_DECIMALS)),
            Capture.expense_date.isnot(None),
        )
        .order_by(Capture.created_at.asc())
        .all()
    )


def retry_failed_captures(db, *, dry_run: bool = False, notify: bool = True) -> dict:
    """Re-drive each retryable failed capture through save_capture_expense.

    Returns a summary dict: {"candidates", "recovered", "still_failed"}.
    """
    candidates = find_retryable(db)
    recovered = 0
    still_failed = 0

    for capture in candidates:
        label = (
            f"capture #{capture.id}: {capture.currency} {capture.amount_str} "
            f"at {capture.merchant or 'unknown'} on {capture.expense_date}"
        )
        if dry_run:
            print(f"[dry-run] would retry {label}")
            continue

        try:
            expense = save_capture_expense(db, capture)
        except Exception as exc:
            db.rollback()
            still_failed += 1
            print(f"[skip]  {label} — still failing: {exc}")
            continue

        recovered += 1
        print(f"[ok]    {label} -> expense #{expense.id}")

        if notify and capture.telegram_chat_id is not None:
            db.add(
                OutboundNotification(
                    telegram_chat_id=capture.telegram_chat_id,
                    body=(
                        f"Recovered an expense that failed earlier: "
                        f"{capture.currency} {capture.amount_str} at "
                        f"{capture.merchant or 'unknown'} on {capture.expense_date}."
                    ),
                )
            )
            db.commit()

    return {
        "candidates": len(candidates),
        "recovered": recovered,
        "still_failed": still_failed,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be retried without changing anything.",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="Recover the expenses silently (do not queue Telegram messages).",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        summary = retry_failed_captures(
            db, dry_run=args.dry_run, notify=not args.no_notify
        )
    finally:
        db.close()

    if args.dry_run:
        print(f"\n{summary['candidates']} capture(s) would be retried.")
    else:
        print(
            f"\nDone. {summary['recovered']} recovered, "
            f"{summary['still_failed']} still failing, "
            f"of {summary['candidates']} candidate(s)."
        )
