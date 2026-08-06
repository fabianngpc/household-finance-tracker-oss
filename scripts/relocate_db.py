"""One-time DB relocation helper: moves the live SQLite database off the
iCloud-synced project folder onto local APFS storage (data safety — keeps the live DB off the
iCloud-synced folder so file-sync races cannot corrupt it).

This script is a GUARD + MOVE, not a full runbook — it does not stop
services, does not edit launchd plists, and does not run alembic. See
DEPLOY.md "DB relocation off iCloud" for the full step-by-step sequence
this script is one step of.

Usage:
    uv run python scripts/relocate_db.py [--from data/finance.db] [--to ~/FinanceAppData/finance.db]

What it does, in order:
1. Refuses to run if --to already exists (never silently overwrites a
   previously-relocated DB).
2. Runs `PRAGMA wal_checkpoint(TRUNCATE)` against --from via a FRESH
   sqlite3 connection (folds any pending WAL pages into the main file and
   truncates -wal to empty — safe to move afterwards).
3. Creates the target directory (mkdir -p) if needed.
4. Moves the .db file, plus any -wal/-shm sidecars if still present.
5. Prints the `export FINANCE_DB_PATH=...` line and the remaining manual
   steps (set FINANCE_DB_PATH in every launchd plist, run
   `alembic upgrade head` as a sanity check, restart services).

Does NOT auto-edit plists — the operator must fill FINANCE_DB_PATH in each
deploy/launchd/com.finance.*.plist by hand (or re-run deploy/install.sh
after editing) so the change is visible and reviewable.
"""
import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

DEFAULT_FROM = "data/finance.db"
DEFAULT_TO = "~/FinanceAppData/finance.db"


def relocate(from_path: str, to_path: str) -> int:
    src = Path(from_path).expanduser().resolve()
    dst = Path(to_path).expanduser()

    if not src.exists():
        print(f"ERROR: source database not found: {src}", file=sys.stderr)
        return 1

    if dst.exists():
        print(
            f"ERROR: target already exists: {dst}\n"
            "Refusing to overwrite an existing (possibly already-relocated) "
            "database. Remove or rename it first if this is intentional.",
            file=sys.stderr,
        )
        return 1

    print(f"Source: {src}")
    print(f"Target: {dst}")

    print("Checkpointing WAL (PRAGMA wal_checkpoint(TRUNCATE))...")
    with sqlite3.connect(str(src)) as conn:
        result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        print(f"  wal_checkpoint result: busy={result[0]} log_pages={result[1]} checkpointed={result[2]}")

    print("Verifying source integrity before move (PRAGMA integrity_check)...")
    with sqlite3.connect(str(src)) as conn:
        check = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            print(f"ERROR: integrity_check failed: {check} — aborting move.", file=sys.stderr)
            return 1
        print("  integrity_check: ok")

    dst.parent.mkdir(parents=True, exist_ok=True)

    print(f"Moving {src.name} -> {dst}")
    shutil.move(str(src), str(dst))

    # Move any sidecar files left behind (wal_checkpoint(TRUNCATE) empties
    # -wal but does not delete it; -shm may also still exist).
    for suffix in ("-wal", "-shm"):
        sidecar = src.with_name(src.name + suffix)
        if sidecar.exists():
            target_sidecar = dst.with_name(dst.name + suffix)
            print(f"Moving sidecar {sidecar.name} -> {target_sidecar}")
            shutil.move(str(sidecar), str(target_sidecar))

    print()
    print("Relocation complete. Remaining manual steps:")
    print(f"  1. export FINANCE_DB_PATH={dst}")
    print("  2. Set FINANCE_DB_PATH to the same path in every")
    print("     deploy/launchd/com.finance.*.plist EnvironmentVariables block.")
    print("  3. Sanity-check migrations against the relocated DB:")
    print(f"       FINANCE_DB_PATH={dst} uv run alembic upgrade head")
    print("  4. Restart all services (deploy/install.sh re-bootstraps the")
    print("     LaunchAgents, or `launchctl kickstart -k gui/$(id -u)/com.finance.<name>`).")
    print()
    print("Note: backups may stay under the iCloud-synced project root — they")
    print("are static, closed snapshots, so syncing them is safe (free offsite copy).")
    print("Only the LIVE database must leave iCloud.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="from_path", default=DEFAULT_FROM,
                         help=f"Source DB path (default: {DEFAULT_FROM})")
    parser.add_argument("--to", dest="to_path", default=DEFAULT_TO,
                         help=f"Target DB path, local APFS, outside iCloud (default: {DEFAULT_TO})")
    args = parser.parse_args(argv)
    return relocate(args.from_path, args.to_path)


if __name__ == "__main__":
    sys.exit(main())
