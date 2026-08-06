"""SQLite backup script using VACUUM INTO.

VACUUM INTO creates a defragmented, consistent copy of a live SQLite WAL database.
It cannot be run inside a transaction — use a fresh sqlite3.connect() (not SQLAlchemy).
Requires SQLite >= 3.27.0, which is bundled with Python 3.8+.
"""
import os
import sqlite3
from datetime import datetime
from pathlib import Path


def backup_database(
    db_path: str | None = None,
    backup_dir: str = "backups",
) -> str:
    """Create a consistent backup of the SQLite database using VACUUM INTO.

    Args:
        db_path: Path to the source database file. Defaults to FINANCE_DB_PATH
            env var (falling back to "data/finance.db") when not given.
        backup_dir: Directory where the backup will be written.

    Returns:
        The path to the created backup file.

    Raises:
        RuntimeError: If the backup integrity check fails.
    """
    if db_path is None:
        db_path = os.environ.get("FINANCE_DB_PATH", "data/finance.db")
    Path(backup_dir).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"finance_{timestamp}.db")

    # Open a FRESH sqlite3 connection — NOT a SQLAlchemy session.
    # VACUUM INTO cannot run inside a transaction; sqlite3.connect() is autocommit by default.
    with sqlite3.connect(db_path) as conn:
        conn.execute(f"VACUUM INTO '{backup_path}'")

    # Verify backup integrity before declaring success.
    with sqlite3.connect(backup_path) as conn:
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if result[0] != "ok":
            raise RuntimeError(f"Backup integrity check failed: {result[0]}")

    return backup_path


def _last_backup_date(backup_dir: str = "backups") -> str:
    """Best-effort 'last good backup' date for the failure-alert copy, derived
    from the newest finance_YYYYMMDD_HHMMSS.db filename still on disk."""
    backups = sorted(Path(backup_dir).glob("finance_*.db"))
    if not backups:
        return "none"
    stamp = backups[-1].stem.removeprefix("finance_")  # "YYYYMMDD_HHMMSS"
    try:
        return datetime.strptime(stamp, "%Y%m%d_%H%M%S").strftime("%Y-%m-%d")
    except ValueError:
        return "unknown"


def backup_with_retention(
    db_path: str | None = None,
    backup_dir: str = "backups",
    keep: int = 14,
) -> str:
    """Checkpoint the WAL into the main DB (clean snapshot), take a VACUUM INTO
    backup with integrity_check, then keep only the newest `keep` snapshots.

    Args:
        db_path: Path to the source database file. Defaults to FINANCE_DB_PATH
            env var (falling back to "data/finance.db") when not given.
        backup_dir: Directory where backups are written/pruned.
        keep: Number of newest backups to retain (older ones are deleted).

    Returns:
        The path to the newly created backup file.

    Raises:
        RuntimeError: If the new backup's integrity check fails (propagated
            from backup_database — no pruning happens in that case).
    """
    if db_path is None:
        db_path = os.environ.get("FINANCE_DB_PATH", "data/finance.db")
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # fold -wal into main; clean snapshot

    path = backup_database(db_path, backup_dir)  # existing VACUUM INTO + integrity_check

    backups = sorted(Path(backup_dir).glob("finance_*.db"))
    for old in backups[:-keep]:  # keep only the newest `keep`
        old.unlink()
    return path


def notify_backup_failure(
    reason: str,
    chat_id: int | None = None,
    backup_dir: str = "backups",
) -> None:
    """Direct httpx call to the Telegram Bot API — no PTB Application/loop is
    ever spun up here. Owner-only, best-effort:
    a failure to *send* the alert is swallowed so it never masks the original
    backup failure being re-raised by the caller."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token or chat_id is None:
        return
    import httpx

    last_good = _last_backup_date(backup_dir)
    text = f"\U0001f534 Backup FAILED: {reason}. Last good backup: {last_good}. Check the Mac mini."
    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except Exception:
        pass  # best-effort — never let alert delivery mask the underlying failure


def run_daily_backup(
    db_path: str | None = None,
    backup_dir: str = "backups",
    keep: int = 14,
    chat_id: int | None = None,
) -> str:
    """Run the checkpoint+backup+prune pipeline; on ANY failure, fire the
    owner Telegram alert (best-effort) and re-raise so the caller/logs see it.
    Success is left to the caller to log (the scheduler logs stdout)."""
    try:
        return backup_with_retention(db_path, backup_dir, keep)
    except Exception as exc:
        notify_backup_failure(str(exc), chat_id, backup_dir)
        raise


if __name__ == "__main__":
    result_path = run_daily_backup()
    print(f"Backup created: {result_path}")
