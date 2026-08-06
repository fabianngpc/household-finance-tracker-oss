"""Short-lived scheduler: generate due recurring occurrences and run the daily
backup. Invoked by launchd StartCalendarInterval (see deploy/launchd for
the plist) — this is NEVER a long-running daemon. Safe to run repeatedly: recurring generation is idempotent
by construction (UNIQUE(rule_id, period_key) in RecurringOccurrence) and the
daily backup is guarded by a once-per-day filename check, so a missed launchd
fire (asleep/off) simply catches up on the next run.
"""
import os
import sys
from datetime import date
from pathlib import Path

from app.database import SessionLocal
from app.models.recurring import RecurringRule
from app.models.user import User
from app.services.recurring import generate_due
from scripts.backup import run_daily_backup


def generate_all(db, today: date | None = None) -> int:
    """Generate due occurrences for every non-paused recurring rule.

    Returns the total number of newly created RecurringOccurrence rows
    across all rules (0 if everything was already generated — idempotent).
    """
    today = today or date.today()
    rules = db.query(RecurringRule).filter(RecurringRule.paused.is_(False)).all()
    created = 0
    for rule in rules:
        created += len(generate_due(db, rule, today=today))
    return created


def already_backed_up_today(backup_dir: str = "backups", today: date | None = None) -> bool:
    """True if a finance_YYYYMMDD_*.db backup already exists for `today` —
    the once-per-day guard so main() never runs backup_with_retention twice
    in the same day even if the scheduler fires more than once."""
    today = today or date.today()
    prefix = f"finance_{today.strftime('%Y%m%d')}_"
    if not Path(backup_dir).exists():
        return False
    return any(Path(backup_dir).glob(f"{prefix}*.db"))


def _resolve_owner_chat() -> int | None:
    """Resolve the owner's Telegram chat id for the backup-failure alert:
    prefer the first linked user's telegram_id; fall back to OWNER_CHAT_ID."""
    db = SessionLocal()
    try:
        user = (
            db.query(User)
            .filter(User.telegram_id.isnot(None))
            .order_by(User.id)
            .first()
        )
        if user is not None:
            return user.telegram_id
    finally:
        db.close()
    env_chat = os.environ.get("OWNER_CHAT_ID")
    return int(env_chat) if env_chat else None


def main(argv=None) -> int:
    db = SessionLocal()
    try:
        created = generate_all(db)
        print(f"Recurring generation: {created} new occurrence(s).")
    finally:
        db.close()

    if already_backed_up_today():
        print("Daily backup already ran today — skipping.")
    else:
        path = run_daily_backup(chat_id=_resolve_owner_chat())
        print(f"Daily backup created: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
