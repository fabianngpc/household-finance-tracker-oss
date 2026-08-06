"""Tests for the SQLite VACUUM INTO backup script.

Verifies:
1. backup_database() creates a file at the expected path.
2. The backup passes PRAGMA integrity_check == "ok".
3. Data is readable from the backup (restore proof).
4. backup_with_retention() checkpoints + prunes to `keep` newest snapshots
   and propagates integrity-check failures as RuntimeError.
5. notify_backup_failure()/run_daily_backup() alert via httpx on failure.
"""
import sqlite3
import os
from pathlib import Path

import pytest

from scripts.backup import (
    backup_database,
    backup_with_retention,
    notify_backup_failure,
    run_daily_backup,
)


def _make_src_db(path: str) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO items (value) VALUES ('retention-test')")
        conn.commit()


def test_backup_creates_file(tmp_path):
    """backup_database returns a path that exists."""
    src = str(tmp_path / "test.db")
    backup_dir = str(tmp_path / "backups")

    # Create a source DB with a table and a row
    with sqlite3.connect(src) as conn:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO items (value) VALUES ('hello')")
        conn.commit()

    backup_path = backup_database(db_path=src, backup_dir=backup_dir)
    assert os.path.exists(backup_path), f"Backup file not found: {backup_path}"


def test_backup_integrity_check(tmp_path):
    """The backup file passes PRAGMA integrity_check."""
    src = str(tmp_path / "test.db")
    backup_dir = str(tmp_path / "backups")

    with sqlite3.connect(src) as conn:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO items (value) VALUES ('world')")
        conn.commit()

    backup_path = backup_database(db_path=src, backup_dir=backup_dir)

    with sqlite3.connect(backup_path) as conn:
        result = conn.execute("PRAGMA integrity_check").fetchone()
    assert result[0] == "ok", f"integrity_check failed: {result[0]}"


def test_backup_restore_readable(tmp_path):
    """Data written to the source DB is readable from the backup (restore proof)."""
    src = str(tmp_path / "test.db")
    backup_dir = str(tmp_path / "backups")

    with sqlite3.connect(src) as conn:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO items (value) VALUES ('restore-proof')")
        conn.commit()

    backup_path = backup_database(db_path=src, backup_dir=backup_dir)

    with sqlite3.connect(backup_path) as conn:
        # Verify integrity_check passes
        result = conn.execute("PRAGMA integrity_check").fetchone()
        assert result[0] == "ok"
        # Read back the row to confirm data is accessible (verified restore)
        row = conn.execute("SELECT value FROM items WHERE value='restore-proof'").fetchone()
    assert row is not None, "Row not found in backup — restore failed"
    assert row[0] == "restore-proof"


def test_retention_prune_keeps_newest_14(tmp_path):
    """20 pre-existing fake backups + 1 new one from backup_with_retention ->
    exactly the newest 14 (by filename/timestamp order) remain."""
    src = str(tmp_path / "test.db")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    _make_src_db(src)

    # 20 fake pre-existing backup files, oldest to newest by filename.
    for day in range(1, 21):
        fake = backup_dir / f"finance_202601{day:02d}_000000.db"
        fake.write_text("fake")

    new_path = backup_with_retention(db_path=src, backup_dir=str(backup_dir), keep=14)

    remaining = sorted(backup_dir.glob("finance_*.db"))
    assert len(remaining) == 14, f"expected 14 remaining, got {len(remaining)}: {remaining}"
    # The newly created backup is the newest and must have survived the prune.
    assert Path(new_path) in remaining
    # The 7 oldest fake files (day 1..7) must be gone.
    for day in range(1, 8):
        assert not (backup_dir / f"finance_202601{day:02d}_000000.db").exists()


def test_retention_prune_integrity_failure_raises(tmp_path, monkeypatch):
    """An integrity-check failure inside backup_database propagates as
    RuntimeError from backup_with_retention (no prune happens)."""
    src = str(tmp_path / "test.db")
    backup_dir = str(tmp_path / "backups")
    _make_src_db(src)

    def _fail_backup(db_path, backup_dir):
        raise RuntimeError("Backup integrity check failed: corrupt")

    monkeypatch.setattr("scripts.backup.backup_database", _fail_backup)

    with pytest.raises(RuntimeError, match="integrity check failed"):
        backup_with_retention(db_path=src, backup_dir=backup_dir, keep=14)


def test_notify_backup_failure_sends_telegram_alert(monkeypatch):
    """notify_backup_failure posts to the Bot API directly via httpx (no PTB)."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    calls = []

    def _fake_post(url, json, timeout):
        calls.append((url, json, timeout))

    monkeypatch.setattr("httpx.post", _fake_post)

    notify_backup_failure("disk full", chat_id=42, backup_dir="backups-does-not-exist")

    assert len(calls) == 1
    url, payload, _timeout = calls[0]
    assert "fake-token" in url
    assert payload["chat_id"] == 42
    assert "disk full" in payload["text"]
    assert "Check the Mac mini" in payload["text"]


def test_notify_backup_failure_noop_without_token_or_chat(monkeypatch):
    """No token or no chat_id -> silently does nothing (never crashes)."""
    calls = []
    monkeypatch.setattr("httpx.post", lambda *a, **k: calls.append(1))

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    notify_backup_failure("reason", chat_id=42)
    assert calls == []

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    notify_backup_failure("reason", chat_id=None)
    assert calls == []


def test_run_daily_backup_success_returns_path(tmp_path):
    src = str(tmp_path / "test.db")
    backup_dir = str(tmp_path / "backups")
    _make_src_db(src)

    path = run_daily_backup(db_path=src, backup_dir=backup_dir, keep=14, chat_id=None)
    assert os.path.exists(path)


def test_run_daily_backup_alerts_and_reraises_on_failure(tmp_path, monkeypatch):
    """Any exception from backup_with_retention triggers the Telegram alert
    (best-effort) and is re-raised so the caller/logs see it."""
    src = str(tmp_path / "test.db")
    backup_dir = str(tmp_path / "backups")
    _make_src_db(src)

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    calls = []
    monkeypatch.setattr("httpx.post", lambda *a, **k: calls.append(1))

    def _fail(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr("scripts.backup.backup_with_retention", _fail)

    with pytest.raises(RuntimeError, match="boom"):
        run_daily_backup(db_path=src, backup_dir=backup_dir, keep=14, chat_id=42)

    assert len(calls) == 1
