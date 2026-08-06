"""
Budget alert engine — deduplicated, race-safe, crash-safe Telegram
alerts for the user-TOTAL budget.

Design rules:
- The `budget_alerts_sent` UNIQUE(user_id, period, threshold) constraint (not
  application logic) is the sole dedup mechanism: `_claim_alert` uses
  INSERT OR IGNORE + rowcount so concurrent writers (web, bot, worker,
  scheduler) racing to claim the same (user, period, threshold) can only ever
  have exactly one winner.
- `check_budget_alerts` NEVER alerts on a backfilled/edited PAST-month write —
  only the CURRENT calendar month (relative to `today`) can trigger an alert.
- Only the user-TOTAL cap (Budget.category_id IS NULL) can trigger an alert;
  a per-category cap being over is silently ignored here (handles
  per-category display separately).
- The claim (sent-flag insert) and the outbound-notification enqueue commit
  in ONE transaction — a crash between claim and commit loses (never
  duplicates) an alert. This function never calls the Telegram API directly;
  delivery is decoupled to bot/worker.py's outbound drain.
"""
from datetime import date

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.budget import Budget
from app.models.notification import OutboundNotification
from app.models.user import User
from app.services.money import format_from_minor_units
from app.services.reports import monthly_summary

BASE_CURRENCY = "SGD"

# 120 = the "over-budget" alert threshold (CONTEXT: tunable, single constant).
ALERT_THRESHOLDS = (80, 100, 120)


def _chat_for_user(db: Session, user_id: int) -> int | None:
    """Resolve a user's Telegram chat id via their linked telegram_id.
    In private chats chat_id == telegram_id."""
    u = db.get(User, user_id)
    return u.telegram_id if u else None


def _alert_body(threshold: int, cap_minor: int, spent_minor: int) -> str:
    """Exact 05-UI-SPEC copy. All amounts via format_from_minor_units(_, 'SGD')."""
    pct = spent_minor * 100 // cap_minor
    cap = format_from_minor_units(cap_minor, BASE_CURRENCY)
    spent = format_from_minor_units(spent_minor, BASE_CURRENCY)

    if threshold == 80:
        left = format_from_minor_units(max(cap_minor - spent_minor, 0), BASE_CURRENCY)
        return (
            f"⚠️ Budget check: you're at {pct}% of your S${cap} monthly "
            f"budget. Spent S${spent}, S${left} left."
        )
    if threshold == 100:
        return (
            f"\U0001f534 Budget reached: you've hit {pct}% of your S${cap} "
            f"monthly budget. Spent S${spent} — you're at the cap."
        )
    # threshold == 120 (or any further over-budget threshold)
    over = format_from_minor_units(max(spent_minor - cap_minor, 0), BASE_CURRENCY)
    return (
        f"\U0001f534 Over budget: you're at {pct}% of your S${cap} monthly "
        f"budget. Spent S${spent} — S${over} over."
    )


def _claim_alert(db: Session, user_id: int, period: str, threshold: int) -> bool:
    """Return True exactly once per (user, period, threshold). The UNIQUE
    constraint arbitrates concurrent writers; only the winner returns True.

    Standalone testable claim helper (concurrency proxy for the double-claim
    test) — commits on its own. check_budget_alerts below does NOT call this;
    it performs the same INSERT OR IGNORE inline so the claim and the
    outbound-notification row can commit together in ONE transaction.
    """
    result = db.execute(
        text(
            "INSERT OR IGNORE INTO budget_alerts_sent(user_id, period, threshold) "
            "VALUES (:u, :p, :t)"
        ),
        {"u": user_id, "p": period, "t": threshold},
    )
    db.commit()
    return result.rowcount == 1


def check_budget_alerts(
    db: Session, user_id: int, occurred_on: date, today: date | None = None
) -> None:
    """
    Decide whether a money write crossed an alert threshold for the user's
    TOTAL budget, and if so, claim the sent-flag + enqueue an outbound
    notification (never send directly).

    Never alerts on a PAST-month occurred_on (backfill/edit guard). No-op if
    the user has no TOTAL budget set. The claim(s) and any outbound-
    notification row(s) commit together in ONE transaction, so a crash loses
    (never duplicates) an alert.
    """
    today = today or date.today()
    if (occurred_on.year, occurred_on.month) != (today.year, today.month):
        return  # never alert on backfilled / edited PAST months

    cap = db.scalar(
        select(Budget.amount_minor).where(
            Budget.user_id == user_id, Budget.category_id.is_(None)
        )
    )
    if not cap:
        return

    spent = monthly_summary(db, today.year, today.month, user_id=user_id)[
        "total_sgd_minor"
    ]
    pct = spent * 100 // cap
    period = f"{today.year:04d}-{today.month:02d}"

    for threshold in ALERT_THRESHOLDS:
        if pct >= threshold:
            result = db.execute(
                text(
                    "INSERT OR IGNORE INTO budget_alerts_sent"
                    "(user_id, period, threshold) VALUES (:u, :p, :t)"
                ),
                {"u": user_id, "p": period, "t": threshold},
            )
            if result.rowcount == 1:  # first crossing this period
                chat_id = _chat_for_user(db, user_id)
                if chat_id is not None:
                    db.add(
                        OutboundNotification(
                            telegram_chat_id=chat_id,
                            body=_alert_body(threshold, cap, spent),
                        )
                    )
    db.commit()  # sent-flag(s) + outbound row(s) commit together (one transaction)
