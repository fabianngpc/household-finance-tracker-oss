# DEPLOY.md — Always-On Deployment Runbook

This is the operator runbook for running the Family Finance Tracker
unattended, 24/7, on a dedicated Mac mini. It covers:
one-time setup, relocating the live database off iCloud, installing the
launchd LaunchAgents, and the verification checklist that confirms the
whole thing actually recovers cleanly on real hardware.

Five processes are supervised by launchd user LaunchAgents:

| Agent | Command | Restart policy |
|---|---|---|
| `com.finance.web` | `uv run uvicorn app.main:app --host 0.0.0.0 --port 8000` | RunAtLoad + KeepAlive |
| `com.finance.bot` | `uv run python -m bot.main` | RunAtLoad + KeepAlive |
| `com.finance.worker` | `uv run python -m bot.worker` | RunAtLoad + KeepAlive |
| `com.finance.ollama` | `ollama serve` | RunAtLoad + KeepAlive |
| `com.finance.scheduler` | `uv run python -m app.scheduler` | StartCalendarInterval (hourly :05 + daily 00:30), no KeepAlive — must exit |

---

## 1. One-time setup

**Enable auto-login.** LaunchAgents (as opposed to LaunchDaemons) only run
while a user is logged into a GUI session — this is required because Apple
Vision OCR (`ocrmac`) and Ollama's model cache (`~/.ollama`) both
need a real user session, not a headless root context. Enable auto-login
for the `YOUR_USERNAME` account in **System Settings → Users & Groups → Login
Options → Automatic login**. This is a deliberate security relaxation,
accepted because the machine is LAN-only and single-household.

**Fill secrets in the plists.** Every `deploy/launchd/com.finance.*.plist`
ships with `__FILL_ME__` placeholders for `SECRET_KEY` and
`TELEGRAM_BOT_TOKEN` — real values must never be committed to git. Edit
each of the five plists in `deploy/launchd/` and replace both placeholders
with the real values from your `.env`. `deploy/install.sh` refuses to run
while any placeholder remains.

**Verify the ollama binary path.** The `com.finance.ollama.plist`
ProgramArguments hardcodes an absolute path (`which ollama` on this repo's
Apple Silicon dev/deploy machine resolved to `/opt/homebrew/bin/ollama`;
Intel Homebrew installs to `/usr/local/bin/ollama` instead). Run
`which ollama` on the target Mac and update the plist if it differs.

**Configure power management.**

```bash
deploy/pmset.sh
```

This sets `sleep 0`, `disksleep 0`, `womp 1` (wake-on-network), `autorestart 1`
(auto power-on after a power loss), and `powernap 0`, then prints `pmset -g`
to verify. Requires `sudo`.

---

## 2. DB relocation off iCloud

The live SQLite database defaults to `data/finance.db`, inside the
iCloud-synced project folder. iCloud can evict, partially-upload, or
replace files while SQLite has them open — a real corruption risk already
observed in this project (iCloud evicting venv files mid-run in Phases 3–5).
The fix: move only the *live* database to local APFS storage, outside any
synced folder. Backups may safely stay in iCloud (they are static, closed
snapshots — a free offsite copy).

Steps:

1. **Stop all services** (skip this the very first time, before anything
   is installed yet):
   ```bash
   deploy/install.sh uninstall
   ```
2. **Run the relocation script:**
   ```bash
   uv run python scripts/relocate_db.py
   ```
   By default this moves `data/finance.db` → `~/FinanceAppData/finance.db`.
   The script refuses to run if the target already exists, checkpoints the
   WAL (`PRAGMA wal_checkpoint(TRUNCATE)`) and verifies integrity before
   moving, then prints the exact `FINANCE_DB_PATH` value and the remaining
   manual steps. It does **not** edit plists or run migrations for you.
3. **Set `FINANCE_DB_PATH` in every plist** — each
   `deploy/launchd/com.finance.*.plist` already ships with
   `FINANCE_DB_PATH=/Users/YOUR_USERNAME/FinanceAppData/finance.db` in its
   `EnvironmentVariables` dict, matching the script's default target. If
   you used a custom `--to`, update all five plists to match.
4. **Sanity-check migrations against the relocated DB:**
   ```bash
   FINANCE_DB_PATH=/Users/YOUR_USERNAME/FinanceAppData/finance.db uv run alembic upgrade head
   ```
   This should report "no changes" (the schema is already current) — it
   confirms `alembic/env.py` is reading the relocated file, not a stale
   copy.
5. **Restart services** — see section 3 below.

---

## 3. Install / start

```bash
deploy/install.sh
```

This copies the five plists from `deploy/launchd/` into
`~/Library/LaunchAgents/`, then `launchctl bootstrap`s each one. It is
idempotent (bootout-then-bootstrap) — safe to re-run after editing a plist.
It refuses to run if any plist still contains `__FILL_ME__`.

Verify each agent loaded:

```bash
launchctl print gui/$(id -u)/com.finance.web
launchctl print gui/$(id -u)/com.finance.bot
launchctl print gui/$(id -u)/com.finance.worker
launchctl print gui/$(id -u)/com.finance.ollama
launchctl print gui/$(id -u)/com.finance.scheduler
```

Each should show `state = running` (or `waiting` for the scheduler,
between calendar fires) and a `pid`.

To uninstall (bootout all five, leaving copied plists in place):

```bash
deploy/install.sh uninstall
```

---

## 4. Verification checklist (manual — see 05-VALIDATION.md "Manual-Only Verifications")

These six behaviors can only be confirmed on real hardware — automated
checks (`plutil -lint`, `grep`, `bash -n`) cover everything else and
already pass.

1. **Boot auto-start.** With auto-login enabled, reboot the Mac
   mini. After it comes back up, confirm all five agents are loaded and
   running:
   ```bash
   launchctl print gui/$(id -u)/com.finance.web
   launchctl print gui/$(id -u)/com.finance.bot
   launchctl print gui/$(id -u)/com.finance.worker
   launchctl print gui/$(id -u)/com.finance.ollama
   launchctl print gui/$(id -u)/com.finance.scheduler
   ```

2. **`kill -9` auto-restart.** Kill a supervised process and
   confirm launchd's `KeepAlive` respawns it within ~12 seconds (well past
   the 10s `ThrottleInterval`):
   ```bash
   pkill -9 -f bot.worker
   sleep 12
   launchctl print gui/$(id -u)/com.finance.worker | grep -i pid
   ```
   Repeat for `com.finance.web` (`pkill -9 -f uvicorn`) and `com.finance.bot`
   (`pkill -9 -f bot.main`). A NEW pid each time confirms the restart. If a
   process respawns every ~10s and immediately dies again, that is a
   crash-loop — check `~/Library/Logs/finance/<name>.err.log` before
   assuming success.

3. **No-sleep.**
   ```bash
   pmset -g
   ```
   Confirm `sleep 0`. Leave the machine idle for a while and confirm the
   web UI and bot still respond (no idle sleep despite no local
   keyboard/mouse activity).

4. **iCloud relocation.** Confirm `FINANCE_DB_PATH` resolves
   outside the iCloud-synced project folder, and that there are no
   `finance.db-wal` / `finance.db-shm` sidecar files anywhere under the
   synced project root:
   ```bash
   echo "$FINANCE_DB_PATH"
   find "$(git rev-parse --show-toplevel)" -maxdepth 2 -name "finance.db*"
   ```
   The second command should print nothing (or only files under a
   `backups/` directory, which is fine — those are static snapshots).

5. **Tested restore.** A destructive but essential test — do
   this on the real deployment, not just in CI:
   ```bash
   deploy/install.sh uninstall
   cp "$FINANCE_DB_PATH" "${FINANCE_DB_PATH}.pre-restore-test.bak"   # safety net
   cp backups/finance_<latest-timestamp>.db "$FINANCE_DB_PATH"
   sqlite3 "$FINANCE_DB_PATH" "PRAGMA integrity_check;"
   deploy/install.sh
   ```
   Confirm `integrity_check` returns `ok`, the app starts, and your data
   (expenses, budgets, recurring rules) looks intact and current as of the
   backup's timestamp. Restore `${FINANCE_DB_PATH}.pre-restore-test.bak`
   back over the live path afterwards if this was just a drill.

6. **Real Telegram delivery + month-boundary dedup.**
   - Cross a real budget threshold (or temporarily set a low cap via the
     web Budgets page) and confirm exactly ONE Telegram alert arrives.
   - Save a second expense in the same period that keeps you over the same
     threshold — confirm NO second alert (dedup holds).
   - Trigger a recurring rule's generation (or wait for the scheduler's
     next fire) and confirm the "Recurring logged" message arrives exactly
     once.
   - If feasible, confirm dedup resets across a real calendar-month
     boundary (a new month re-arms all three thresholds); otherwise this
     can be simulated by inspecting `budget_alerts_sent` rows for two
     different `period` values.

---

## 5. Logs & troubleshooting

All five agents log to `~/Library/Logs/finance/<name>.{out,err}.log`:

```bash
tail -f ~/Library/Logs/finance/web.err.log
tail -f ~/Library/Logs/finance/bot.err.log
tail -f ~/Library/Logs/finance/worker.err.log
tail -f ~/Library/Logs/finance/ollama.err.log
tail -f ~/Library/Logs/finance/scheduler.err.log
```

**Crash-loop warning sign.** launchd's default `ThrottleInterval` is 10
seconds — a hard crash-loop respawns roughly every 10s. If
`launchctl print gui/$(id -u)/com.finance.<name>` shows a fresh pid every
~10s, the process is crashing immediately on start, not running normally.
Check the matching `.err.log` first.

**Common pitfalls:**
- **Wrong/relative `uv` or `ollama` path** — launchd runs with a minimal
  `PATH`; every plist must use an absolute binary path (already done in
  `deploy/launchd/*.plist`) — do not "simplify" this later.
- **Missing `EnvironmentVariables`** — `SECRET_KEY`, `TELEGRAM_BOT_TOKEN`,
  and `FINANCE_DB_PATH` must all be set in every plist; a missing
  `SECRET_KEY` breaks session cookies, a missing `TELEGRAM_BOT_TOKEN`
  breaks the bot/worker/alert delivery.
- **`WorkingDirectory` mismatch** — must be the exact repo path (note the
  spaces in `.../com~apple~CloudDocs/FINANCE APP`); a wrong working
  directory breaks relative imports and `.env` loading.
- **LaunchDaemon instead of LaunchAgent** — never switch these to
  LaunchDaemons; Apple Vision OCR and Ollama need a real GUI login
  session, which LaunchDaemons (root, pre-login) don't have.
